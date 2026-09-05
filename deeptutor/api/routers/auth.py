"""Auth router — login, logout, status, registration, profile, and user-management endpoints.

Modified from DeepTutor (Apache-2.0, https://github.com/HKUDS/DeepTutor).
Original copyright: 2025 Data Intelligence Lab, The University of Hong Kong.
This file was modified by yuweijiang0803 for the K12 teaching-engine fork:
added the XiaoZhi (manager-web) SSO login bridge endpoint
POST /api/v1/auth/xiaozhi-login. See git history and NOTICE for details.
"""

from contextvars import Token as _CtxToken
import json
import logging
import os
import re
import secrets

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, field_validator

from deeptutor.services.config import load_auth_settings

# SameSite=None lets the cookie work when the browser accesses the frontend via
# 127.0.0.1 and the backend via localhost (different origins on the same machine).
# Browsers require Secure=True for SameSite=None, but that needs HTTPS — so in
# local dev we fall back to SameSite=Lax and tell users to use localhost:// URLs.
_SECURE = bool(load_auth_settings()["cookie_secure"])
_SAMESITE = "none" if _SECURE else "lax"

from deeptutor.multi_user.context import set_current_user, user_from_token_payload
from deeptutor.multi_user.paths import local_admin_user
from deeptutor.services.auth import (
    AUTH_ENABLED,
    POCKETBASE_ENABLED,
    TOKEN_EXPIRE_HOURS,
    TokenPayload,
    add_user,
    authenticate,
    authenticate_pb,
    create_token,
    decode_token,
    delete_user,
    get_user_info,
    is_first_user,
    list_users,
    register_pb,
    set_avatar,
    set_role,
)
from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.codex_auth.service import deliver_codex_oauth_callback

logger = logging.getLogger(__name__)

router = APIRouter()

_COOKIE_NAME = "dt_token"
_COOKIE_MAX_AGE = TOKEN_EXPIRE_HOURS * 3600


def _cookie_attrs() -> dict:
    """Attribute set shared by ``login``'s ``set_cookie`` and ``logout``'s
    ``delete_cookie``.

    The deletion ``Set-Cookie`` must carry the same attributes as the one
    that created the cookie — ``delete_cookie`` defaults ``secure=False``,
    which browsers reject when paired with ``SameSite=None``, silently
    keeping the old cookie. See #623. Reads the module globals at call time
    so tests can monkeypatch ``_SECURE``/``_SAMESITE``.
    """
    return {
        "key": _COOKIE_NAME,
        "httponly": True,
        "samesite": _SAMESITE,
        "secure": _SECURE,
    }


# 与 manager（小智）共享的统一登录 cookie 作用域：mix-token 下在 .hourofai.cn
# 顶级域，manager-web / DeepTutor / OpenMAIC 通用（可用 XIAOZHI_COOKIE_DOMAIN 覆盖）。
_SHARED_COOKIE_DOMAIN = (
    os.environ.get("XIAOZHI_COOKIE_DOMAIN", "").strip() or "hourofai.cn"
)

# DT 表单用 manager 账号登录时，代理到 manager 的登录接口建立中心会话。
# 部署时可用 MANAGER_LOGIN_URL 覆盖（如 https://manager.hourofai.cn/api/login）。
MANAGER_LOGIN_URL = (
    os.environ.get("MANAGER_LOGIN_URL", "").strip()
    or "http://manager:8084/api/login"
)


def _set_shared_login_cookie(response: Response, token: str) -> None:
    """种下与 manager 一致的共享登录 cookie ``mix-token``。

    httpOnly:false 与 manager 后端一致（manager-web 的 JS 守卫/登出依赖可读可清），
    域名取共享顶级域；这样 DT 用 manager 账号登录后，manager/OpenMAIC 也处于登录态。
    """
    response.set_cookie(
        key="mix-token",
        value=token,
        max_age=24 * 3600,
        path="/",
        domain=_SHARED_COOKIE_DOMAIN,
        httponly=False,
        samesite="lax",
        secure=_SECURE,
    )


def _expire_cookie(response: Response, name: str, domain: str = "") -> None:
    """Send an expiring Set-Cookie (path=/). ``domain`` = "" keeps it host-only."""
    response.set_cookie(
        key=name,
        value="",
        max_age=0,
        expires=0,
        path="/",
        domain=domain or None,
        httponly=True,
        samesite="lax",
        secure=_SECURE,
    )


def _clear_shared_login_cookies(response: Response) -> None:
    """平台级统一登出：清掉共享的 manager ``mix-token``（host-only + 顶级域各变体，
    覆盖不同下发方式/本地开发），并顺带清理遗留的 dt_logged_out 标记。"""
    _expire_cookie(response, "mix-token", "")
    _expire_cookie(response, "mix-token", _SHARED_COOKIE_DOMAIN)
    _expire_cookie(response, "mix-token", f".{_SHARED_COOKIE_DOMAIN}")
    _expire_cookie(response, "dt_logged_out", "")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Payload for the POST /login endpoint."""

    username: str
    password: str


class RegisterRequest(BaseModel):
    """Payload for the POST /register endpoint."""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        import re

        v = v.strip()
        if not v:
            raise ValueError("Email cannot be empty")
        # Accept standard email addresses (used by PocketBase mode) or plain
        # usernames (used by the built-in SQLite/JSON auth mode).
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        plain_re = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")
        if not email_re.match(v) and not plain_re.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class SetRoleRequest(BaseModel):
    """Payload for the PUT /users/{username}/role endpoint."""

    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ("admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class AuthStatusResponse(BaseModel):
    """Response body for the GET /status endpoint."""

    enabled: bool
    authenticated: bool
    user_id: str | None = None
    username: str | None = None
    role: str | None = None
    is_admin: bool = False
    avatar: str = ""
    nickname: str = ""


class UserInfo(BaseModel):
    """Single user record returned by the GET /users and /profile endpoints."""

    id: str = ""
    username: str
    role: str
    created_at: str
    disabled: bool = False
    avatar: str = ""
    nickname: str = ""


# Markers settable through PUT /profile. Image markers ("img:<version>") are
# managed exclusively by the upload endpoint so users cannot point their
# avatar at a file that was never validated.
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")

# User ids are generated as "u_<uuid hex>" (plus the "local-admin" /
# "env-admin" sentinels); reject anything else before it reaches the
# filesystem layer.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UpdateProfileRequest(BaseModel):
    """Payload for the PUT /profile endpoint."""

    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v: str) -> str:
        v = v.strip()
        if v and not _ICON_MARKER_RE.match(v):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return v


# ---------------------------------------------------------------------------
# Shared helper — extract token from cookie or Bearer header
# ---------------------------------------------------------------------------


def _bearer_token_from_header(authorization: str | None) -> str | None:
    """Parse ``Authorization: Bearer <token>`` without using ``HTTPBearer``.

    ``HTTPBearer`` is a class-based dependency whose ``__call__`` is annotated
    ``request: Request``. FastAPI doesn't inject a Request into WebSocket
    dependency resolution, which makes ``HTTPBearer`` raise ``TypeError`` the
    moment a router with this dep mounts a WS endpoint. Doing the parse by
    hand keeps ``require_auth`` HTTP/WS-symmetric.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


def _extract_token(authorization: str | None, dt_token: str | None) -> str | None:
    return _bearer_token_from_header(authorization) or dt_token


# ---------------------------------------------------------------------------
# Dependencies — reusable auth guards for other routers
# ---------------------------------------------------------------------------


def _install_current_user(payload: TokenPayload | None) -> _CtxToken:
    """Install the request-local current-user ContextVar from an auth result.

    Single point of truth for ``payload → CurrentUser`` so HTTP and WebSocket
    entry points produce identical user objects. ``payload is None`` means
    "no JWT was required" (AUTH_ENABLED=false) and resolves to the local
    admin user; a non-None payload resolves through ``user_from_token_payload``.

    Returns the ContextVar reset token. HTTP callers ignore it (the request
    ends with the task, so the var is GC'd with the task context). WebSocket
    callers keep it and call ``reset_current_user`` in their ``finally`` block,
    because a WS connection outlives the dependency-resolution task.

    ⚠ Invariant: every authenticated entry point MUST call this before the
    handler runs. Skipping it leaves ``get_current_path_service()`` falling
    back to the admin workspace — the silent-routing root cause of #481.
    """
    user = local_admin_user() if payload is None else user_from_token_payload(payload)
    return set_current_user(user)


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> TokenPayload | None:
    """
    FastAPI dependency that enforces authentication when AUTH_ENABLED=true.

    Accepts the JWT from either:
      - Authorization: Bearer <token> header
      - dt_token cookie

    ``Header`` and ``Cookie`` are kept here in place of ``HTTPBearer`` so the
    function stays usable from WebSocket call sites that don't go through
    FastAPI's standard HTTP request lifecycle.

    Returns the authenticated TokenPayload, or None if auth is disabled.
    Raises HTTP 401 if auth is enabled but the token is missing or invalid.

    Declared ``async def`` so the ``set_current_user`` call runs in the same
    asyncio context as the endpoint. A sync dependency is dispatched via
    ``anyio.to_thread.run_sync``, which executes the function in a worker
    thread under a *copy* of the request context; any ``ContextVar.set``
    inside that thread is discarded when the thread returns, leaving the
    endpoint to read the unset default. That regression was the root cause
    of #481.
    """
    if not AUTH_ENABLED:
        _install_current_user(None)
        return None

    # Browsing is open to signed-out visitors on every storage mode: they get
    # a guest identity (no data in MySQL-backed stores, no admin access; the
    # chat composer gates sending on login). ``require_signed_in`` below still
    # demands a real account for operations that need one.
    token = _extract_token(authorization, dt_token)
    if not token:
        from deeptutor.multi_user.paths import guest_user

        _install_current_user(guest_user())
        return None

    payload = decode_token(token)
    if not payload:
        from deeptutor.multi_user.paths import guest_user

        _install_current_user(guest_user())
        return None

    _install_current_user(payload)
    return payload


async def require_signed_in(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> TokenPayload | None:
    """Like ``require_auth`` but never falls back to local admin.

    Used by operations that need a real account identity — enabling/disabling
    sync, where every migrated row must belong to a specific XiaoZhi user.
    """
    token = _extract_token(authorization, dt_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录 XiaoZhi 账号",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _install_current_user(payload)
    return payload


class _WsAuthFailed:
    """Sentinel: ws_require_auth failed and closed the WebSocket."""


ws_auth_failed: _WsAuthFailed = _WsAuthFailed()


async def ws_require_auth(ws: WebSocket) -> _CtxToken | _WsAuthFailed:
    """Authenticate a WebSocket connection and set the user ContextVar.

    Must be called **before** ``ws.accept()`` so the server can reject
    unauthenticated upgrades cleanly.

    Returns a ContextVar reset token on success, or ``ws_auth_failed``
    on failure (the WebSocket is already closed — the caller should
    ``return`` immediately).

    Usage::

        user_token = await ws_require_auth(ws)
        if user_token is ws_auth_failed:
            return
        await ws.accept()
        try:
            ...
        finally:
            reset_current_user(user_token)
    """
    if not AUTH_ENABLED:
        return _install_current_user(None)

    # Signed-out visitors may hold a socket for browsing; sending a message is
    # gated by the chat composer's login prompt.
    token = ws.query_params.get("token") or ws.cookies.get(_COOKIE_NAME)
    payload = decode_token(token) if token else None
    if not payload:
        from deeptutor.multi_user.paths import guest_user

        return _install_current_user(guest_user())

    return _install_current_user(payload)


async def require_admin(
    payload: TokenPayload | None = Depends(require_auth),
) -> TokenPayload:
    """
    FastAPI dependency that requires the caller to be an admin.

    Raises HTTP 403 if the authenticated user is not an admin.
    When AUTH_ENABLED=false, all requests are treated as admin.

    ``async def`` mirrors ``require_auth`` so the dependency chain stays on
    the event loop and the user ContextVar set by ``require_auth`` is visible
    to the endpoint.
    """
    if not AUTH_ENABLED:
        return _local_admin_token_payload()

    if payload is None or payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return payload


def _local_admin_token_payload() -> TokenPayload:
    """Synthetic admin payload used when AUTH_ENABLED=false.

    Mirrors the local admin identity (LOCAL_ADMIN_USERNAME / LOCAL_ADMIN_ID)
    so audit logs and self-reference checks behave the same as in multi-user
    mode. Values are kept aligned with ``local_admin_user()`` in
    ``deeptutor/multi_user/paths.py``.
    """
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME

    return TokenPayload(
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        user_id=LOCAL_ADMIN_ID,
    )


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@router.get("/openai-codex/callback")
async def receive_codex_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    headers = {"Cache-Control": "no-store"}
    try:
        callback_state = state if len(request.query_params.getlist("state")) == 1 else None
        await deliver_codex_oauth_callback(code, callback_state, error)
    except CodexAuthError as exc:
        return HTMLResponse(
            (
                "<!doctype html><title>DeepTutor Codex</title>"
                "<p>Authentication could not be received. Return to DeepTutor and try again.</p>"
            ),
            status_code=exc.http_status,
            headers=headers,
        )
    return HTMLResponse(
        (
            "<!doctype html><title>DeepTutor Codex</title>"
            "<p>Authentication received. You can return to DeepTutor.</p>"
        ),
        headers=headers,
    )


async def _resolve_sso_status(
    request: Request,
    response: Response,
    authorization: str | None,
    dt_cookie: str | None,
) -> AuthStatusResponse:
    """解析当前登录态；未带有效 ``dt_token`` 但带 manager ``mix-token`` 时自动交换。

    /status 与 /sso 共用同一实现，确保任何直连 /status 的首次加载（如直接
    fetchAuthStatus 的组件）也能在同一个请求里完成 SSO 交换，不再需要第二次刷新。
    """
    if not AUTH_ENABLED:
        return AuthStatusResponse(
            enabled=False,
            authenticated=True,
            user_id="local-admin",
            username="local",
            role="admin",
            is_admin=True,
        )

    from deeptutor.services.session.mysql_store import mysql_configured

    # LOCAL_MODE（未启用 MySQL 同步）也允许主动登录/SSO：返回真实账号信息；
    # enabled 仍按既有口径上报，避免改变前端对本地模式的判断。
    enabled = bool(mysql_configured())

    def build(payload_: TokenPayload | None) -> AuthStatusResponse:
        if payload_ is None:
            return AuthStatusResponse(enabled=enabled, authenticated=False)
        info = get_user_info(payload_.username) or {}
        return AuthStatusResponse(
            enabled=enabled,
            authenticated=True,
            user_id=payload_.user_id,
            username=payload_.username,
            role=payload_.role,
            is_admin=payload_.role == "admin",
            avatar=str(info.get("avatar") or ""),
            nickname=str(info.get("nickname") or ""),
        )

    token = _extract_token(authorization, dt_cookie)
    payload = decode_token(token) if token else None

    # 无有效 dt 会话：尝试用 manager 身份自动登录（URL ?token= 优先，其次
    # 同源 mix-token cookie），同一请求内完成交换并写入 dt_token。
    manager_token = (
        request.query_params.get("token")
        or request.cookies.get("mix-token")
        or ""
    ).strip()
    decoded = _decode_xiaozhi_token(manager_token)

    if payload is not None and payload.username.startswith("xz_"):
        # SSO 影子会话与 manager 中心会话绑定：中心 mix-token 缺失或不是同一账号
        # 即视为登出（统一登出：任一平台登出清 mix-token 后，DT 下次校验同步退出）。
        # DT 表单用 manager 账号登录会先建中心会话再建影子会话，因此这里的判定
        # 不会误杀刚完成的登录。
        if decoded is None:
            response.delete_cookie(**_cookie_attrs())
            logger.info("SSO shadow session cleared: no valid manager session")
            return build(None)
        if str(decoded[0]) != payload.username[len("xz_"):]:
            # 换了一个 manager 账号：清掉旧 dt 会话，下面重新交换到新账号。
            response.delete_cookie(**_cookie_attrs())
            payload = None

    if payload is not None:
        return build(payload)

    if decoded is not None:
        xz_user_id, manager_role = decoded
        try:
            result = await _complete_xz_login(
                xz_user_id, response, manager_role=manager_role
            )
            logger.info(f"auto-SSO xz_user={xz_user_id!r}")
            return build(
                TokenPayload(
                    username=result["username"],
                    role=result["role"],
                    user_id=result["user_id"],
                )
            )
        except Exception:
            # 交换失败（如账号创建异常）静默降级为未登录，不阻塞页面。
            logger.warning(
                "auto-SSO exchange failed for xz_user=%r", xz_user_id, exc_info=True
            )
    return build(None)


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> AuthStatusResponse:
    """Return whether auth is enabled and whether the current request is authenticated.

    未登录但浏览器带 manager ``mix-token`` 时，会在该请求内自动完成 SSO 交换
    （与 /sso 相同），因此首次加载即可返回登录态，无需二次刷新。
    """
    return await _resolve_sso_status(request, response, authorization, dt_token)


@router.get("/sso", response_model=AuthStatusResponse)
async def sso_bootstrap(request: Request, response: Response) -> AuthStatusResponse:
    """每页加载自动登录（与 OpenMAIC 的 SsoBootstrap 对齐）。

    1. 已有有效 ``dt_token`` → 直接返回当前登录态；
    2. 否则若浏览器带 manager 的 ``mix-token``（cookie 或 ?token=）→ 自动交换成
       DeepTutor 会话并写入 ``dt_token``；
    3. 都不满足 → 未登录（访客浏览，发消息等写操作再要求登录）。
    """
    return await _resolve_sso_status(
        request, response, None, request.cookies.get(_COOKIE_NAME)
    )


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Validate credentials and set a JWT cookie."""
    if not AUTH_ENABLED:
        return {"ok": True, "message": "Auth is disabled — no login required."}

    if POCKETBASE_ENABLED:
        # PocketBase mode: email = username field for backwards-compat with the
        # existing LoginRequest schema; users can pass their email as "username".
        pb_result = authenticate_pb(body.username, body.password)
        if not pb_result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        payload, pb_token = pb_result
        response.set_cookie(value=pb_token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
        logger.info(f"User '{payload.username}' logged in via PocketBase (role={payload.role!r})")
        return {
            "ok": True,
            "user_id": payload.user_id,
            "username": payload.username,
            "role": payload.role,
            "is_admin": payload.role == "admin",
        }

    # Standard JWT + bcrypt mode (DeepTutor's own accounts).
    result = authenticate(body.username, body.password)
    if result:
        token = create_token(result.username, result.role, result.user_id)
        response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
        logger.info(f"User '{result.username}' logged in (role={result.role!r})")
        return {
            "ok": True,
            "user_id": result.user_id,
            "username": result.username,
            "role": result.role,
            "is_admin": result.role == "admin",
        }

    # manager（小智）账号：代理到 manager 登录接口建立「中心会话」，保证全平台
    # 统一——成功后浏览器同时种上共享 mix-token（manager/OpenMAIC 跟着登录）与
    # DT 会话（xz_ 影子账号），登出任意一处即全平台登出。
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                MANAGER_LOGIN_URL,
                json={"username": body.username, "password": body.password},
            )
            data = resp.json() if resp.content else {}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="manager 登录服务暂不可用，请稍后再试",
        )
    if resp.status_code != 200 or not data.get("success") or not data.get("access_token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(data.get("message") or "账号或密码错误"),
        )
    access_token = str(data["access_token"])
    decoded = _decode_xiaozhi_token(access_token)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )
    xz_user_id, manager_role = decoded
    _set_shared_login_cookie(response, access_token)
    return await _complete_xz_login(xz_user_id, response, manager_role=manager_role)


# ---------------------------------------------------------------------------
# XiaoZhi (manager-web) SSO login bridge — fork addition
# ---------------------------------------------------------------------------


class XiaoZhiLoginRequest(BaseModel):
    """Body of ``POST /api/v1/auth/xiaozhi-login``: the XiaoZhi ``mix-token``."""

    token: str = ""


def _xiaozhi_jwt_secret() -> str:
    """Shared JWT secret used to verify XiaoZhi tokens.

    Read from the ``XIAOZHI_JWT_SECRET`` env var, falling back to
    ``data/user/settings/xiaozhi.json`` (``{"jwt_secret": "..."}``).
    """
    secret = os.environ.get("XIAOZHI_JWT_SECRET", "").strip()
    if secret:
        return secret
    try:
        from deeptutor.services.path_service import get_path_service

        cfg = get_path_service().get_user_root() / "settings" / "xiaozhi.json"
        if cfg.exists():
            return str(json.loads(cfg.read_text(encoding="utf-8")).get("jwt_secret") or "")
    except Exception:
        pass
    return ""


async def _find_dt_user_id(xz_user_id: str) -> str:
    """Return ``mixly.user.dt_user_id`` for a XiaoZhi user, or ``""``."""
    from deeptutor.services.session.mysql_store import get_mysql_pool

    pool = await get_mysql_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT dt_user_id FROM `user` WHERE id = %s", (xz_user_id,)
            )
            row = await cur.fetchone()
            return str(row["dt_user_id"]) if row and row.get("dt_user_id") else ""


async def _set_dt_user_id(xz_user_id: str, dt_user_id: str) -> None:
    """Back-fill ``mixly.user.dt_user_id`` for a XiaoZhi user."""
    from deeptutor.services.session.mysql_store import get_mysql_pool

    pool = await get_mysql_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE `user` SET dt_user_id = %s WHERE id = %s",
                (dt_user_id, xz_user_id),
            )
        await conn.commit()


async def _find_xz_nickname(xz_user_id: str) -> str:
    """Return the XiaoZhi display nickname for a user, or ``""``."""
    from deeptutor.services.session.mysql_store import get_mysql_pool

    try:
        pool = await get_mysql_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT nickname FROM `user` WHERE id = %s", (xz_user_id,)
                )
                row = await cur.fetchone()
                return str(row["nickname"]) if row and row.get("nickname") else ""
    except Exception:
        # SSO must not fail because the nickname lookup did — fall back to the
        # xz_<id> username.
        return ""


async def _xiaozhi_verify_credentials(username: str, password: str) -> str:
    """Verify a XiaoZhi (``mixly.user``) account by username + password.

    XiaoZhi stores ``md5(password + salt)`` (see manager ``util.md5_str``).
    Returns the XiaoZhi user id on success, ``""`` otherwise. Mirrors the
    manager's own login check so the DeepTutor login form can accept XiaoZhi
    credentials directly.
    """
    import hashlib

    from deeptutor.services.session.mysql_store import mysql_configured

    if not mysql_configured():
        return ""
    from deeptutor.services.session.mysql_store import get_mysql_pool

    try:
        pool = await get_mysql_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, password, salt FROM `user` WHERE username = %s",
                    (username,),
                )
                row = await cur.fetchone()
                if not row:
                    return ""
                hashed = hashlib.md5(
                    (password + str(row["salt"] or "")).encode("utf-8")
                ).hexdigest()
                return str(row["id"]) if hashed == str(row["password"] or "") else ""
    except Exception:
        return ""


async def _complete_xz_login(
    xz_user_id: str,
    response: Response,
    *,
    manager_role: str = "",
) -> dict:
    """Create/refresh the ``xz_<id>`` shadow user and sign the DeepTutor token.

    Shared by the XiaoZhi SSO endpoint and the login form's XiaoZhi-account
    branch. Keeps any existing role (an admin promoted in DeepTutor must not be
    demoted by a re-login) and syncs the display nickname from XiaoZhi.

    角色映射：manager ``admin`` → DeepTutor ``admin``，其余角色 → ``user``；
    已在 DeepTutor 手动提升为 admin 的影子账号不降级。SSO 不依赖 MySQL：
    昵称/映射回填仅在 mysql 可用时尽力而为，失败不影响登录。
    """
    dt_username = f"xz_{xz_user_id}"

    existing = get_user_info(dt_username) or {}
    existing_role = str(existing.get("role") or "user")
    if existing_role == "admin" or (manager_role == "admin" and existing_role != "admin"):
        effective_role = "admin"
    else:
        effective_role = "user"

    nickname = ""
    from deeptutor.services.session.mysql_store import mysql_configured

    if mysql_configured():
        try:
            nickname = await _find_xz_nickname(xz_user_id)
        except Exception:
            nickname = ""

    # The random password is irrelevant — XiaoZhi-account users never use it.
    add_user(dt_username, secrets.token_urlsafe(24), role=effective_role, nickname=nickname)
    dt_user_id = _shadow_user_id(dt_username) or str(existing.get("id") or "")
    if dt_user_id and mysql_configured():
        try:
            await _set_dt_user_id(xz_user_id, dt_user_id)
        except Exception:
            # 回填 mixly.user 是纯加分项；失败不阻塞 SSO。
            pass

    token = create_token(dt_username, effective_role, dt_user_id)
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
    logger.info(f"XiaoZhi user '{xz_user_id}' logged in as DeepTutor '{dt_username}'")
    return {
        "ok": True,
        "user_id": dt_user_id,
        "username": dt_username,
        "role": effective_role,
        "is_admin": effective_role == "admin",
    }


def _shadow_user_id(username: str) -> str:
    """Id of a DeepTutor shadow user by username, or ``""``."""
    try:
        from deeptutor.services.auth import _load_users

        return str((_load_users().get(username) or {}).get("id") or "")
    except Exception:
        return ""


def _decode_xiaozhi_token(token: str) -> tuple[str, str] | None:
    """Verify a manager ``mix-token`` (HS256 共享密钥). Returns ``(xz_user_id,
    manager_role)`` on success, else ``None``."""
    secret = _xiaozhi_jwt_secret()
    if not token or not secret:
        return None
    try:
        from jose import jwt

        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None
    if payload.get("v") != 1:
        return None
    ident = payload.get("i") or []
    if not ident:
        return None
    xz_user_id = str(ident[0])
    # i = [user_id, role_id, role, clase, school]（与 OpenMAIC verifyManagerToken 一致）
    manager_role = str(ident[2]) if len(ident) >= 3 else ""
    return xz_user_id, manager_role


@router.post("/xiaozhi-login")
async def xiaozhi_login(body: XiaoZhiLoginRequest, response: Response) -> dict:
    """Exchange a XiaoZhi (manager-web) ``mix-token`` for a DeepTutor session.

    1. Verifies the token with the shared JWT secret（与 OpenMAIC 同机制）。
    2. Maps ``xz_user_id`` → DeepTutor shadow user（username ``xz_<xz_user_id>``，
       本地 users.json，不依赖 MySQL）。
    3. On first login, auto-creates the shadow user and back-fills
       ``mixly.user.dt_user_id`` when MySQL is available（尽力而为）。
    4. Signs a DeepTutor token and sets it as the ``dt_token`` cookie.
    """
    decoded = _decode_xiaozhi_token(body.token)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid XiaoZhi token",
        )
    xz_user_id, manager_role = decoded
    logger.info(f"SSO xz_user={xz_user_id!r}")
    return await _complete_xz_login(xz_user_id, response, manager_role=manager_role)


@router.post("/logout")
async def logout(response: Response) -> dict:
    """平台级统一登出：清掉共享的 manager ``mix-token``（多个 domain 变体）和
    DeepTutor 自己的 ``dt_token``。

    与 OpenMAIC / manager-web 一致——任一平台登出即整组账号体系登出：新页面
    读不到 mix-token 就不会再自动登录回来。不再设置 ``dt_logged_out`` 抑制标记
    （那会阻止 manager 重新登录后的自动 SSO）。

    ``dt_token`` 的删除属性镜像写入属性（见 ``_cookie_attrs`` 说明 #623）。
    """
    response.delete_cookie(**_cookie_attrs())
    _clear_shared_login_cookies(response)
    return {"ok": True}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> dict:
    """
    Bootstrap-only registration.

    Public endpoint that creates the *first* admin account when the user store
    is empty. Once an admin exists, this endpoint is closed; further accounts
    must be created by an admin via ``POST /api/v1/auth/users``.

    Only available when AUTH_ENABLED=true.
    """
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — registration is not available.",
        )

    if POCKETBASE_ENABLED:
        # PocketBase deployments are documented as single-user. Keep registration
        # closed and require admins to provision users in the PocketBase admin UI.
        if not is_first_user():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Self-registration is closed. Ask an administrator to create your account.",
            )
        result = register_pb(username=body.username, email=body.username, password=body.password)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registration failed — username or email may already be taken.",
            )
        logger.info(f"First user registered via PocketBase: '{body.username}'")
        return {
            "ok": True,
            "user_id": result.get("id", ""),
            "username": body.username,
            "role": "user",
            "is_first_user": True,
            "is_admin": False,
        }

    # Standard mode — only allowed before the first admin exists.
    if not is_first_user():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is closed. Ask an administrator to create your account.",
        )

    existing = {u["username"] for u in list_users()}
    if body.username in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    add_user(body.username, body.password)
    user_id = ""
    role = "user"
    for item in list_users():
        if item.get("username") == body.username:
            user_id = str(item.get("id") or "")
            role = str(item.get("role") or "user")
            break
    logger.info(f"First user (admin) registered: '{body.username}'")
    return {
        "ok": True,
        "user_id": user_id,
        "username": body.username,
        "role": role,
        "is_first_user": True,
        "is_admin": role == "admin",
    }


@router.get("/is_first_user")
async def check_is_first_user() -> dict:
    """Return whether the user store is empty (used by the register UI)."""
    return {"is_first_user": is_first_user() if AUTH_ENABLED else False}


# ---------------------------------------------------------------------------
# Profile endpoints (any authenticated user, self-service)
# ---------------------------------------------------------------------------

_AVATAR_MAX_BYTES = 1 * 1024 * 1024
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _sniff_image(data: bytes) -> str | None:
    """Detect a supported raster image format from its magic bytes.

    The uploaded filename and Content-Type are attacker-controlled, so the
    stored extension (and the media type served back) is derived from the
    bytes alone. SVG is deliberately unsupported — serving user-supplied SVG
    is a stored-XSS vector.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _require_profile_identity(payload: TokenPayload | None) -> TokenPayload:
    """Shared guard for the self-service profile endpoints."""
    if not AUTH_ENABLED or payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — profiles are not available.",
        )
    return payload


@router.get("/profile", response_model=UserInfo)
async def get_profile(
    payload: TokenPayload | None = Depends(require_signed_in),
) -> UserInfo:
    """Return the current user's own account info."""
    current = _require_profile_identity(payload)
    info = get_user_info(current.username)
    if info is None:
        # PocketBase-backed identities have no local record; fall back to the
        # token claims so the profile page still renders.
        return UserInfo(
            id=current.user_id,
            username=current.username,
            role=current.role,
            created_at="",
        )
    return UserInfo(**info)


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    payload: TokenPayload | None = Depends(require_signed_in),
) -> dict:
    """Update the current user's own avatar marker (icon choice or reset).

    Only the validated ``icon:<name>:<color>`` form (or empty string) is
    accepted here; ``img:`` markers are owned by the upload endpoint.
    """
    current = _require_profile_identity(payload)
    if not set_avatar(current.username, body.avatar):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # The marker no longer references an uploaded image, so drop the file.
    from deeptutor.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    return {"ok": True, "avatar": body.avatar}


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    payload: TokenPayload | None = Depends(require_signed_in),
) -> dict:
    """Upload an avatar image for the current user.

    The client is expected to crop/resize before uploading; the server only
    enforces a size cap and validates the format by magic bytes. Not available
    in PocketBase mode (those identities have no local user record).
    """
    current = _require_profile_identity(payload)
    if POCKETBASE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar upload is not available in PocketBase mode.",
        )
    if not current.user_id or not _USER_ID_RE.match(current.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot store an avatar for this account.",
        )
    info = get_user_info(current.username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Avatar image is too large (max 1 MB).",
        )
    ext = _sniff_image(data)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be a PNG, JPEG or WebP image.",
        )

    from deeptutor.multi_user.identity import save_avatar_file

    # Bump the version embedded in the marker so clients cache-bust the URL.
    previous = str(info.get("avatar") or "")
    version = 1
    if previous.startswith("img:"):
        try:
            version = int(previous.split(":", 1)[1]) + 1
        except ValueError:
            version = 1
    marker = f"img:{version}"

    save_avatar_file(current.user_id, data, ext)
    if not set_avatar(current.username, marker):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info(f"User '{current.username}' uploaded a new avatar ({ext}, {len(data)} bytes)")
    return {"ok": True, "avatar": marker}


@router.delete("/profile/avatar")
async def remove_avatar(
    payload: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Remove the current user's uploaded avatar image and reset the marker."""
    current = _require_profile_identity(payload)
    from deeptutor.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    set_avatar(current.username, "")
    return {"ok": True, "avatar": ""}


@router.get("/avatar/{user_id}")
async def get_avatar_image(
    user_id: str,
    _: TokenPayload | None = Depends(require_auth),
) -> FileResponse:
    """Serve a stored avatar image. Any authenticated user may view avatars
    (they appear in the admin table and next to the viewer's own profile)."""
    if not _USER_ID_RE.match(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    from deeptutor.multi_user.identity import get_avatar_file

    target = get_avatar_file(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    media_type = _AVATAR_MEDIA_TYPES.get(target.suffix.lstrip("."), "application/octet-stream")
    headers = {
        # Private user content; the marker version in the URL handles busting.
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    return FileResponse(path=str(target), media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# Admin-only endpoints
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserInfo])
async def get_users(_: TokenPayload = Depends(require_admin)) -> list[UserInfo]:
    """List all registered users. Requires admin role."""
    return [UserInfo(**u) for u in list_users()]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: RegisterRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Admin-only: create a new user account.

    Replaces the public ``/register`` flow once the first admin exists. The
    new account is always created with role=``user``; admins can promote
    later via ``PUT /users/{username}/role``.
    """
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — user creation is not available.",
        )

    if POCKETBASE_ENABLED:
        result = register_pb(username=body.username, email=body.username, password=body.password)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Failed to create user — username may already be taken.",
            )
        logger.info(
            f"Admin '{current.username if current else 'local'}' created PocketBase user "
            f"'{body.username}'"
        )
        return {
            "ok": True,
            "user_id": result.get("id", ""),
            "username": body.username,
            "role": "user",
            "is_admin": False,
        }

    existing = {u["username"] for u in list_users()}
    if body.username in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    add_user(body.username, body.password)
    user_id = ""
    role = "user"
    for item in list_users():
        if item.get("username") == body.username:
            user_id = str(item.get("id") or "")
            role = str(item.get("role") or "user")
            break
    logger.info(
        f"Admin '{current.username if current else 'local'}' created user '{body.username}' "
        f"(role={role!r})"
    )
    return {
        "ok": True,
        "user_id": user_id,
        "username": body.username,
        "role": role,
        "is_admin": role == "admin",
    }


@router.delete("/users/{username}", status_code=status.HTTP_200_OK)
async def remove_user(
    username: str,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Delete a user. Admins cannot delete their own account."""
    if current and username == current.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )

    # Capture the id before the record disappears so the avatar file can go too.
    info = get_user_info(username)

    removed = delete_user(username)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_id = str(info.get("id") or "") if info else ""
    if user_id and _USER_ID_RE.match(user_id):
        from deeptutor.multi_user.identity import delete_avatar_file

        delete_avatar_file(user_id)

    logger.info(f"Admin '{current.username if current else 'local'}' deleted user '{username}'")
    return {"ok": True}


@router.put("/users/{username}/role", status_code=status.HTTP_200_OK)
async def update_user_role(
    username: str,
    body: SetRoleRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Change a user's role. Admins cannot change their own role."""
    if current and username == current.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role",
        )

    updated = set_role(username, body.role)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(
        f"Admin '{current.username if current else 'local'}' set '{username}' role to {body.role!r}"
    )
    return {"ok": True, "username": username, "role": body.role}
