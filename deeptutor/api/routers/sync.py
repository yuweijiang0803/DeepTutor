"""LOCAL_MODE sync-mode control endpoints.

- ``GET  /api/v1/sync/status``  — which storage mode is active.
- ``POST /api/v1/sync/enable``  — persist MySQL settings, migrate local data up.
- ``POST /api/v1/sync/disable`` — optionally pull data back, switch to local.

Both mutating endpoints require a signed-in user (their id becomes the owner
of every migrated row on the server).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.config.runtime_settings import (
    load_mysql_settings,
    save_mysql_settings,
)
from deeptutor.services.session.mysql_store import mysql_configured
from deeptutor.services.sync import (
    migrate_local_to_server,
    migrate_server_to_local,
)

router = APIRouter()


class MySqlConnection(BaseModel):
    host: str = ""
    port: int = 3306
    user: str = ""
    password: str = ""
    database: str = "mixly"


class SyncEnableRequest(BaseModel):
    mysql: MySqlConnection | None = None


class SyncDisableRequest(BaseModel):
    pull_first: bool = Field(default=False, description="Pull server data back to local before disabling.")


def _current_mode() -> str:
    return "sync" if mysql_configured() else "local"


@router.get("/status")
async def sync_status() -> dict[str, Any]:
    cfg = load_mysql_settings()
    return {
        "mode": _current_mode(),
        "synced": bool(cfg.get("enabled")) and bool(cfg.get("host")),
        "host": cfg.get("host", "") if mysql_configured() else "",
    }


@router.post("/enable", dependencies=[Depends(require_auth)])
async def enable_sync(body: SyncEnableRequest) -> dict[str, Any]:
    """Turn sync mode on: enable the pre-provisioned MySQL connection and
    migrate local conversations / question bank / mastery paths up under the
    signed-in user's id. Idempotent — if already synced, returns the current
    state.

    The server connection itself (host/port/user/password) is provisioned at
    deploy time (mysql.json / env vars), not entered by the end user — the
    user only signs in and flips the switch."""
    if mysql_configured():
        return {"mode": "sync", "already_enabled": True}

    cfg = load_mysql_settings()
    if not cfg.get("host"):
        raise HTTPException(
            status_code=400,
            detail="未配置同步服务器连接，请联系管理员预置 MySQL 配置。",
        )
    # An explicit connection in the request overrides the provisioned one
    # (used by admins / deployments that hand the client the settings).
    if body.mysql is not None and body.mysql.host:
        cfg = {
            **cfg,
            "host": body.mysql.host,
            "port": body.mysql.port,
            "user": body.mysql.user,
            "password": body.mysql.password,
            "database": body.mysql.database or cfg.get("database") or "mixly",
        }

    save_mysql_settings({**cfg, "enabled": True})

    try:
        report = await migrate_local_to_server()
    except Exception as exc:
        # Roll the switch back so a failed migration never leaves the app
        # half-switched (some data local, some on the server). The provisioned
        # connection info is kept so the user can simply retry.
        save_mysql_settings({**load_mysql_settings(), "enabled": False})
        raise HTTPException(status_code=500, detail=f"Migration failed: {type(exc).__name__}: {exc}") from exc

    return {"mode": "sync", "already_enabled": False, "report": report.to_dict()}


@router.post("/disable", dependencies=[Depends(require_auth)])
async def disable_sync(body: SyncDisableRequest) -> dict[str, Any]:
    """Turn sync mode off. By default server data stays on the server; pass
    ``pull_first: true`` to copy it back into the local store first."""
    if not mysql_configured():
        return {"mode": "local", "already_disabled": True}

    report = None
    if body.pull_first:
        try:
            report = await migrate_server_to_local()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Pull-back failed: {type(exc).__name__}: {exc}") from exc

    # Only flip the switch — keep the provisioned connection so re-enabling
    # needs no re-entry.
    save_mysql_settings({**load_mysql_settings(), "enabled": False})
    return {"mode": "local", "already_disabled": False, "report": report.to_dict() if report else None}
