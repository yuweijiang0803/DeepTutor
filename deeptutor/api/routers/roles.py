"""Current-organisation-identity (role switching) endpoints.

Leverages the XiaoZhi (manager-web) organisation: ``mixly.roles`` maps a user
to multiple ``school`` / ``clase`` / ``role`` rows (a user can be a teacher in
one class and a student in another). DeepTutor stores the *active* identity
per-user in ``users.json`` and exposes it so the frontend can switch
identities; the active identity decides which class's shared knowledge base
and learning data the user sees.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from deeptutor.services.auth import TokenPayload
from deeptutor.api.routers.auth import require_auth

router = APIRouter()

_DT_XZ_PREFIX = "xz_"


def _xz_user_id_from_username(username: str) -> str:
    """Map a DeepTutor ``xz_<id>`` username back to the XiaoZhi user id."""
    if username.startswith(_DT_XZ_PREFIX):
        return username[len(_DT_XZ_PREFIX):]
    return ""


async def _fetch_roles(xz_user_id: str) -> list[dict[str, Any]]:
    """Return the user's XiaoZhi organisational identities (school/clase/role)."""
    from deeptutor.services.session.mysql_store import get_mysql_pool, mysql_configured

    if not mysql_configured() or not xz_user_id:
        return []
    try:
        pool = await get_mysql_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT r.school, r.clase, r.role, r.expired_at,
                           s.name AS school_name, c.name AS clase_name
                    FROM roles r
                    LEFT JOIN school s ON s.id = r.school
                    LEFT JOIN clase c ON c.id = r.clase
                    WHERE r.user_id = %s
                      AND (r.expired_at IS NULL OR r.expired_at > NOW())
                    ORDER BY r.school, r.clase
                    """,
                    (xz_user_id,),
                )
                rows = await cur.fetchall()
        return [
            {
                "school_id": str(row.get("school") or ""),
                "school_name": str(row.get("school_name") or ""),
                "clase_id": str(row.get("clase") or ""),
                "clase_name": str(row.get("clase_name") or ""),
                "role": str(row.get("role") or ""),
            }
            for row in rows
        ]
    except Exception:
        # Role listing must never break the UI — fall back to an empty list.
        return []


def _active_identity(username: str) -> dict[str, Any] | None:
    from deeptutor.multi_user.identity import get_active_role

    return get_active_role(username)


@router.get("")
async def list_roles(payload: TokenPayload | None = Depends(require_auth)) -> dict[str, Any]:
    """Return every identity the user holds in the XiaoZhi organisation."""
    username = str(payload.username if payload else "")
    xz_user_id = _xz_user_id_from_username(username)
    return {"roles": await _fetch_roles(xz_user_id)}


@router.get("/active")
async def get_active_role(payload: TokenPayload | None = Depends(require_auth)) -> dict[str, Any]:
    """Return the user's active identity, defaulting to the first role."""
    username = str(payload.username if payload else "")
    xz_user_id = _xz_user_id_from_username(username)
    roles = await _fetch_roles(xz_user_id)
    active = _active_identity(username)
    if active is None and roles:
        active = roles[0]
    return {"active_role": active, "roles": roles}


@router.post("/active")
async def set_active_role(body: dict[str, Any], payload: TokenPayload | None = Depends(require_auth)) -> dict[str, Any]:
    """Switch the user's active identity. The body must match one of the
    identities returned by ``GET /roles`` (school_id + clase_id + role)."""
    from deeptutor.multi_user.identity import set_active_role as _store_active_role

    username = str(payload.username if payload else "")
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    xz_user_id = _xz_user_id_from_username(username)
    roles = await _fetch_roles(xz_user_id)
    requested = {
        "school_id": str(body.get("school_id") or ""),
        "clase_id": str(body.get("clase_id") or ""),
        "role": str(body.get("role") or ""),
    }
    valid = any(
        r["school_id"] == requested["school_id"]
        and r["clase_id"] == requested["clase_id"]
        and r["role"] == requested["role"]
        for r in roles
    )
    if not valid:
        raise HTTPException(status_code=400, detail="Requested identity is not one of this user's roles")

    if not _store_active_role(username, requested):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "active_role": requested}
