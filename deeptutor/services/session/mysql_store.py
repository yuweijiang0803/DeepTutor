"""
Copyright 2026 yuweijiang0803

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

MySQL-backed session store.

Implements :class:`SessionStoreProtocol` against a shared MySQL database so
conversation records live in the same MySQL as the XiaoZhi (manager-web)
management platform.

Storage model
-------------
* Every table carries a ``user_id`` column. All reads/writes are scoped by
  ``_current_user_id()`` — the same ContextVar the SQLite/PocketBase backends
  resolve against — so one user can never read or mutate another user's rows.
* Times are stored as epoch ``DOUBLE`` (matching SQLite's ``REAL``).
* JSON-shaped fields (events/attachments/metadata/preferences) are stored as
  TEXT and (de)serialised identically to the SQLite backend.
* Table names use a ``dt_`` prefix so the DeepTutor tables never collide with
  existing XiaoZhi business tables in the shared ``mixly`` database.

Notebook tables are intentionally NOT mirrored here: notebook/question-bank
tools call ``get_sqlite_session_store()`` directly and stay on SQLite.

Connection configuration comes from environment variables:

    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration + pool
# ---------------------------------------------------------------------------


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _mysql_settings() -> dict[str, Any]:
    """MySQL session-store config: mysql.json settings, env vars win."""
    try:
        from deeptutor.services.config.runtime_settings import load_mysql_settings

        cfg = dict(load_mysql_settings())
    except Exception:
        cfg = {"enabled": False, "host": "", "port": 3306, "user": "", "password": "", "database": ""}
    if _env("MYSQL_HOST"):
        cfg["enabled"] = True
        cfg["host"] = _env("MYSQL_HOST")
        cfg["port"] = int(_env("MYSQL_PORT", "3306"))
        cfg["user"] = _env("MYSQL_USER")
        cfg["password"] = _env("MYSQL_PASSWORD")
        cfg["database"] = _env("MYSQL_DB")
    return cfg


def mysql_configured() -> bool:
    """True when the MySQL session store should be used."""
    cfg = _mysql_settings()
    return bool(cfg.get("enabled")) and bool(cfg.get("host"))


def storage_mode() -> str:
    """Storage mode: ``"local"`` | ``"dual"`` | ``"mysql"``.

    - ``local`` — no MySQL configured (PC default): everything stays in the
      local SQLite store, no login needed.
    - ``dual`` — MySQL configured with ``dual: true`` (PC sync enabled):
      reads come from local SQLite, writes go to both local and MySQL.
    - ``mysql`` — MySQL configured without dual (web/server deployment):
      reads and writes all go to MySQL, login required.
    """
    if not mysql_configured():
        return "local"
    return "dual" if _mysql_settings().get("dual") else "mysql"


_pool: Any = None


async def get_mysql_pool():
    """Return a lazily-created aiomysql connection pool."""
    global _pool
    if _pool is None:
        import aiomysql

        cfg = _mysql_settings()
        _pool = await aiomysql.create_pool(
            host=cfg.get("host") or "127.0.0.1",
            port=int(cfg.get("port") or 3306),
            user=cfg.get("user") or "root",
            password=cfg.get("password") or "",
            db=cfg.get("database") or "mixly",
            minsize=1,
            maxsize=8,
            charset="utf8mb4",
            # autocommit=True so every statement is immediately durable and
            # reads always see the latest committed rows. With autocommit=False
            # a read method that returns without commit/rollback leaves a
            # stale REPEATABLE-READ snapshot on the pooled connection, so a
            # session created by one method becomes invisible to the next
            # method that reuses that connection ("Session not found").
            autocommit=True,
            cursorclass=aiomysql.DictCursor,
        )
        await _ensure_schema(_pool)
    return _pool


async def close_mysql_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dt_sessions (
    id                   VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    title                VARCHAR(255) NOT NULL DEFAULT 'New conversation',
    created_at           DOUBLE       NOT NULL,
    updated_at           DOUBLE       NOT NULL,
    compressed_summary   MEDIUMTEXT,
    summary_up_to_msg_id BIGINT       NOT NULL DEFAULT 0,
    preferences_json     MEDIUMTEXT   NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dt_sessions_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_messages (
    id                 BIGINT       NOT NULL AUTO_INCREMENT,
    session_id         VARCHAR(64)  NOT NULL,
    user_id            VARCHAR(64)  NOT NULL,
    role               VARCHAR(16)  NOT NULL,
    content            MEDIUMTEXT   NOT NULL,
    capability         VARCHAR(32)  NOT NULL DEFAULT '',
    events_json        MEDIUMTEXT,
    attachments_json   MEDIUMTEXT,
    metadata_json      MEDIUMTEXT,
    created_at         DOUBLE       NOT NULL,
    parent_message_id  BIGINT       NULL,
    PRIMARY KEY (id),
    KEY idx_dt_messages_session (session_id, created_at, id),
    KEY idx_dt_messages_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_turns (
    id          VARCHAR(64) NOT NULL,
    session_id  VARCHAR(64) NOT NULL,
    user_id     VARCHAR(64) NOT NULL,
    capability  VARCHAR(32) NOT NULL DEFAULT '',
    status      VARCHAR(16) NOT NULL DEFAULT 'running',
    error       TEXT,
    created_at  DOUBLE      NOT NULL,
    updated_at  DOUBLE      NOT NULL,
    finished_at DOUBLE      NULL,
    PRIMARY KEY (id),
    KEY idx_dt_turns_session (session_id, updated_at),
    KEY idx_dt_turns_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_turn_events (
    id            BIGINT      NOT NULL AUTO_INCREMENT,
    turn_id       VARCHAR(64) NOT NULL,
    seq           INT         NOT NULL,
    type          VARCHAR(32) NOT NULL,
    source        VARCHAR(64) NOT NULL DEFAULT '',
    stage         VARCHAR(32) NOT NULL DEFAULT '',
    content       MEDIUMTEXT,
    metadata_json TEXT        NOT NULL,
    timestamp     DOUBLE      NOT NULL,
    created_at    DOUBLE      NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_dt_turn_events (turn_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


async def _ensure_schema(pool) -> None:
    import warnings

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for stmt in _SCHEMA.split(";"):
                if stmt.strip():
                    # CREATE TABLE IF NOT EXISTS on an existing table makes
                    # MySQL return a benign "already exists" warning; suppress
                    # it so startup logs stay quiet.
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        await cur.execute(stmt)
        await conn.commit()
    logger.info("[mysql_store] schema ensured (dt_sessions/dt_messages/dt_turns/dt_turn_events)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Unset:
    """Sentinel: distinguish "auto-chain parent" from an explicit ``None``."""


_PARENT_AUTO = _Unset()


def _json_dumps(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return ""


def _json_loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _current_user_id() -> str:
    """Id of the request-scoped current user, used to isolate every row."""
    from deeptutor.multi_user.context import get_current_user

    return get_current_user().id


def _new_session_id() -> str:
    return f"unified_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _new_turn_id() -> str:
    return f"turn_{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}"


class MySQLSessionStore:
    """MySQL-backed implementation of SessionStoreProtocol."""

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        pool = await get_mysql_pool()
        now = time.time()
        resolved_id = session_id or _new_session_id()
        resolved_title = (title or "New conversation").strip() or "New conversation"
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO dt_sessions (
                        id, user_id, title, created_at, updated_at,
                        compressed_summary, summary_up_to_msg_id, preferences_json
                    ) VALUES (%s, %s, %s, %s, %s, '', 0, %s)
                    """,
                    (resolved_id, user_id, resolved_title, now, now, "{}"),
                )
            await conn.commit()
        return {
            "id": resolved_id,
            "session_id": resolved_id,
            "title": resolved_title,
            "created_at": now,
            "updated_at": now,
            "compressed_summary": "",
            "summary_up_to_msg_id": 0,
            "status": "idle",
            "active_turn_id": "",
            "capability": "",
            "preferences": {},
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT s.id, s.title, s.created_at, s.updated_at,
                           s.compressed_summary, s.summary_up_to_msg_id,
                           s.preferences_json,
                           COALESCE((SELECT t.status FROM dt_turns t
                                     WHERE t.session_id = s.id
                                     ORDER BY t.updated_at DESC LIMIT 1), 'idle') AS status,
                           COALESCE((SELECT t.id FROM dt_turns t
                                     WHERE t.session_id = s.id AND t.status = 'running'
                                     ORDER BY t.updated_at DESC LIMIT 1), '') AS active_turn_id,
                           COALESCE((SELECT t.capability FROM dt_turns t
                                     WHERE t.session_id = s.id
                                     ORDER BY t.updated_at DESC LIMIT 1), '') AS capability
                    FROM dt_sessions s
                    WHERE s.id = %s AND s.user_id = %s
                    """,
                    (session_id, user_id),
                )
                row = await cur.fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["session_id"] = payload["id"]
        payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
        return payload

    async def ensure_session(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session()

    async def update_session_title(self, session_id: str, title: str) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE dt_sessions SET title = %s, updated_at = %s WHERE id = %s AND user_id = %s",
                    (title, time.time(), session_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM dt_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, title, created_at, updated_at, compressed_summary,
                           summary_up_to_msg_id, preferences_json
                    FROM dt_sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (user_id, int(limit), int(offset)),
                )
                rows = await cur.fetchall()
        out = []
        for row in rows:
            payload = dict(row)
            payload["session_id"] = payload["id"]
            payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
            out.append(payload)
        return out

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dt_sessions
                    SET compressed_summary = %s, summary_up_to_msg_id = %s, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (summary, int(up_to_msg_id), time.time(), session_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE dt_sessions SET preferences_json = %s WHERE id = %s AND user_id = %s",
                    (_json_dumps(preferences or {}), session_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        session["active_turns"] = await self.list_active_turns(session_id)
        return session

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def create_turn(
        self,
        session_id: str,
        capability: str = "",
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        pool = await get_mysql_pool()
        now = time.time()
        # An explicit turn_id lets the dual store mirror the local turn's id so
        # events written later land on the same turn server-side.
        resolved_turn_id = turn_id or _new_turn_id()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM dt_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                if await cur.fetchone() is None:
                    raise ValueError(f"Session not found: {session_id}")
                await cur.execute(
                    """
                    SELECT id FROM dt_turns
                    WHERE session_id = %s AND status = 'running'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (session_id,),
                )
                if await cur.fetchone() is not None:
                    raise RuntimeError(f"Session already has an active turn: {session_id}")
                await cur.execute(
                    """
                    INSERT INTO dt_turns (id, session_id, user_id, capability, status, error,
                                          created_at, updated_at, finished_at)
                    VALUES (%s, %s, %s, %s, 'running', '', %s, %s, NULL)
                    """,
                    (resolved_turn_id, session_id, user_id, capability or "", now, now),
                )
            await conn.commit()
        return {
            "id": resolved_turn_id,
            "turn_id": resolved_turn_id,
            "session_id": session_id,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
        }

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT t.id, t.session_id, t.capability, t.status, t.error,
                           t.created_at, t.updated_at, t.finished_at,
                           COALESCE((SELECT MAX(e.seq) FROM dt_turn_events e
                                     WHERE e.turn_id = t.id), 0) AS last_seq
                    FROM dt_turns t
                    JOIN dt_sessions s ON s.id = t.session_id
                    WHERE t.id = %s AND s.user_id = %s
                    """,
                    (turn_id, user_id),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return self._serialize_turn(row)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT t.id, t.session_id, t.capability, t.status, t.error,
                           t.created_at, t.updated_at, t.finished_at,
                           COALESCE((SELECT MAX(e.seq) FROM dt_turn_events e
                                     WHERE e.turn_id = t.id), 0) AS last_seq
                    FROM dt_turns t
                    JOIN dt_sessions s ON s.id = t.session_id
                    WHERE t.session_id = %s AND t.status = 'running' AND s.user_id = %s
                    ORDER BY t.updated_at DESC LIMIT 1
                    """,
                    (session_id, user_id),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return self._serialize_turn(row)

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT t.id, t.session_id, t.capability, t.status, t.error,
                           t.created_at, t.updated_at, t.finished_at,
                           COALESCE((SELECT MAX(e.seq) FROM dt_turn_events e
                                     WHERE e.turn_id = t.id), 0) AS last_seq
                    FROM dt_turns t
                    JOIN dt_sessions s ON s.id = t.session_id
                    WHERE t.session_id = %s AND t.status = 'running' AND s.user_id = %s
                    ORDER BY t.updated_at DESC
                    """,
                    (session_id, user_id),
                )
                rows = await cur.fetchall()
        return [self._serialize_turn(r) for r in rows]

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        now = time.time()
        finished_at = now if status in ("done", "failed", "cancelled") else None
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE dt_turns t
                    JOIN dt_sessions s ON s.id = t.session_id
                    SET t.status = %s, t.error = %s, t.updated_at = %s,
                        t.finished_at = COALESCE(t.finished_at, %s)
                    WHERE t.id = %s AND s.user_id = %s
                    """,
                    (status, error or "", now, finished_at, turn_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Turn events
    # ------------------------------------------------------------------

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        persisted = await self.append_turn_events(turn_id, [event])
        return persisted[0] if persisted else event

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        pool = await get_mysql_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM dt_turn_events WHERE turn_id = %s",
                    (turn_id,),
                )
                last_seq = (await cur.fetchone())["COALESCE(MAX(seq), 0)"]
                now = time.time()
                persisted = []
                for idx, event in enumerate(events):
                    seq = last_seq + idx + 1
                    payload = {
                        "id": None,
                        "turn_id": turn_id,
                        "seq": seq,
                        "type": str(event.get("type") or ""),
                        "source": str(event.get("source") or ""),
                        "stage": str(event.get("stage") or ""),
                        "content": str(event.get("content") or ""),
                        "metadata": event.get("metadata") or {},
                        "timestamp": float(event.get("timestamp") or now),
                        "created_at": now,
                    }
                    await cur.execute(
                        """
                        INSERT IGNORE INTO dt_turn_events (
                            turn_id, seq, type, source, stage, content,
                            metadata_json, timestamp, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            turn_id, seq, payload["type"], payload["source"],
                            payload["stage"], payload["content"],
                            _json_dumps(payload["metadata"]),
                            payload["timestamp"], payload["created_at"],
                        ),
                    )
                    if cur.rowcount > 0:
                        payload["id"] = cur.lastrowid
                        persisted.append(payload)
            await conn.commit()
        return persisted

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT e.id, e.turn_id, e.seq, e.type, e.source, e.stage,
                           e.content, e.metadata_json, e.timestamp, e.created_at
                    FROM dt_turn_events e
                    JOIN dt_turns t ON t.id = e.turn_id
                    JOIN dt_sessions s ON s.id = t.session_id
                    WHERE e.turn_id = %s AND e.seq > %s AND s.user_id = %s
                    ORDER BY e.seq ASC
                    """,
                    (turn_id, int(after_seq), user_id),
                )
                rows = await cur.fetchall()
        out = []
        for row in rows:
            payload = dict(row)
            payload["metadata"] = _json_loads(payload.pop("metadata_json", ""), {})
            out.append(payload)
        return out

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int | str:
        pool = await get_mysql_pool()
        now = time.time()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM dt_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                if await cur.fetchone() is None:
                    raise ValueError(f"Session not found: {session_id}")
                if isinstance(parent_message_id, _Unset):
                    await cur.execute(
                        "SELECT id FROM dt_messages WHERE session_id = %s ORDER BY id DESC LIMIT 1",
                        (session_id,),
                    )
                    last = await cur.fetchone()
                    resolved_parent = int(last["id"]) if last else None
                else:
                    resolved_parent = (
                        int(parent_message_id) if parent_message_id is not None else None
                    )
                await cur.execute(
                    """
                    INSERT INTO dt_messages (
                        session_id, user_id, role, content, capability, events_json,
                        attachments_json, metadata_json, created_at, parent_message_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id, user_id, role, content or "", capability or "",
                        _json_dumps(events or []), _json_dumps(attachments or []),
                        _json_dumps(metadata or {}), now, resolved_parent,
                    ),
                )
                new_id = int(cur.lastrowid)
                await cur.execute(
                    "UPDATE dt_sessions SET updated_at = %s WHERE id = %s AND user_id = %s",
                    (now, session_id, user_id),
                )
            await conn.commit()
        return new_id

    async def delete_message(self, message_id: int | str) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    DELETE m FROM dt_messages m
                    JOIN dt_sessions s ON s.id = m.session_id
                    WHERE m.id = %s AND s.user_id = %s
                    """,
                    (int(message_id), user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if role is None:
                    await cur.execute(
                        """
                        SELECT id, session_id, role, content, capability, events_json,
                               attachments_json, metadata_json, created_at, parent_message_id
                        FROM dt_messages m JOIN dt_sessions s ON s.id = m.session_id
                        WHERE m.session_id = %s AND s.user_id = %s
                        ORDER BY m.id DESC LIMIT 1
                        """,
                        (session_id, user_id),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT id, session_id, role, content, capability, events_json,
                               attachments_json, metadata_json, created_at, parent_message_id
                        FROM dt_messages m JOIN dt_sessions s ON s.id = m.session_id
                        WHERE m.session_id = %s AND m.role = %s AND s.user_id = %s
                        ORDER BY m.id DESC LIMIT 1
                        """,
                        (session_id, role, user_id),
                    )
                row = await cur.fetchone()
        if not row:
            return None
        return self._serialize_message(row)

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT m.id, m.session_id, m.role, m.content, m.capability,
                           m.events_json, m.attachments_json, m.metadata_json,
                           m.created_at, m.parent_message_id
                    FROM dt_messages m JOIN dt_sessions s ON s.id = m.session_id
                    WHERE m.session_id = %s AND s.user_id = %s
                    ORDER BY m.id ASC
                    """,
                    (session_id, user_id),
                )
                rows = await cur.fetchall()
        return [self._serialize_message(r) for r in rows]

    async def get_messages_for_context(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        # MySQL store treats the linear thread as the context path: the
        # edit-branching tree (get_message_path) is SQLite-only. If a leaf is
        # given, only include messages up to it (inclusive) to bound context.
        all_messages = await self.get_messages(session_id)
        if leaf_message_id is None:
            return all_messages
        ids = {m["id"] for m in all_messages}
        if leaf_message_id not in ids:
            return all_messages
        out: list[dict[str, Any]] = []
        for m in all_messages:
            out.append(m)
            if m["id"] == leaf_message_id:
                break
        return out

    async def get_session_with_messages_extra(self, session_id: str) -> dict[str, Any] | None:
        # Alias kept for symmetry with SQLite's convenience surface.
        return await self.get_session_with_messages(session_id)

    # ------------------------------------------------------------------
    # Turn-by-message deletion (mirrors SQLite)
    # ------------------------------------------------------------------

    async def delete_turn_by_message(
        self, session_id: str, message_id: int
    ) -> dict[str, Any]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT m.id, m.session_id, m.role, m.attachments_json, m.created_at
                    FROM dt_messages m JOIN dt_sessions s ON s.id = m.session_id
                    WHERE m.id = %s AND m.session_id = %s AND s.user_id = %s
                    """,
                    (int(message_id), session_id, user_id),
                )
                msg = await cur.fetchone()
                if msg is None:
                    return {
                        "deleted": False,
                        "attachment_ids": [],
                        "turn_id": None,
                        "was_running": False,
                    }
                role = msg["role"]
                paired = None
                if role == "user":
                    await cur.execute(
                        """
                        SELECT id FROM dt_messages
                        WHERE session_id = %s AND role = 'assistant' AND id > %s
                        ORDER BY id ASC LIMIT 1
                        """,
                        (session_id, int(message_id)),
                    )
                    paired = await cur.fetchone()
                elif role == "assistant":
                    await cur.execute(
                        """
                        SELECT id FROM dt_messages
                        WHERE session_id = %s AND role = 'user' AND id < %s
                        ORDER BY id DESC LIMIT 1
                        """,
                        (session_id, int(message_id)),
                    )
                    paired = await cur.fetchone()
                ids_to_delete = {int(message_id)}
                if paired is not None:
                    ids_to_delete.add(int(paired["id"]))
                attachment_ids: list[str] = []
                for row in await self._fetch_messages_by_ids(cur, session_id, ids_to_delete):
                    attachments = _json_loads(row.get("attachments_json"), [])
                    attachment_ids.extend(
                        a.get("id") or a.get("file_id") for a in attachments if isinstance(a, dict)
                    )

                await cur.execute(
                    """
                    SELECT t.id, t.status FROM dt_turns t
                    JOIN dt_sessions s ON s.id = t.session_id
                    WHERE t.session_id = %s AND s.user_id = %s
                    ORDER BY t.updated_at DESC LIMIT 1
                    """,
                    (session_id, user_id),
                )
                turn = await cur.fetchone()
                turn_id = turn["id"] if turn else None
                was_running = bool(turn and turn["status"] == "running")

                # Cascade: delete messages, then any turn attached to this
                # session (approximation of the SQLite "delete turn" behavior).
                if ids_to_delete:
                    fmt = ",".join(["%s"] * len(ids_to_delete))
                    await cur.execute(
                        f"DELETE FROM dt_messages WHERE id IN ({fmt})", list(ids_to_delete)
                    )
                if turn_id:
                    await cur.execute("DELETE FROM dt_turns WHERE id = %s", (turn_id,))
            await conn.commit()
        return {
            "deleted": True,
            "attachment_ids": [x for x in attachment_ids if x],
            "turn_id": turn_id,
            "was_running": was_running,
        }

    async def _fetch_messages_by_ids(
        self, cur, session_id: str, ids: set[int]
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        fmt = ",".join(["%s"] * len(ids))
        await cur.execute(
            f"SELECT id, attachments_json FROM dt_messages WHERE session_id = %s AND id IN ({fmt})",
            [session_id, *sorted(ids)],
        )
        return await cur.fetchall()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_turn(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "turn_id": row["id"],
            "session_id": row["session_id"],
            "capability": row["capability"] or "",
            "status": row["status"] or "running",
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row.get("finished_at"),
            "last_seq": int(row.get("last_seq") or 0),
        }

    @staticmethod
    def _serialize_message(row: dict[str, Any]) -> dict[str, Any]:
        parent = row.get("parent_message_id")
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "capability": row["capability"] or "",
            "events": _json_loads(row.get("events_json"), []),
            "attachments": _json_loads(row.get("attachments_json"), []),
            "metadata": _json_loads(row.get("metadata_json"), {}),
            "created_at": row["created_at"],
            "parent_message_id": int(parent) if parent is not None else None,
        }

    # ------------------------------------------------------------------
    # Question bank (notebook_entries) — dt_notebook_entries
    # ------------------------------------------------------------------

    async def upsert_notebook_entries(self, session_id: str, items: list[dict[str, Any]]) -> int:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        now = time.time()
        upserted = 0
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM dt_sessions WHERE id=%s AND user_id=%s",
                    (session_id, user_id),
                )
                if not await cur.fetchone():
                    raise ValueError(f"Session not found: {session_id}")
                for item in items:
                    question = (item.get("question") or "").strip()
                    question_id = (item.get("question_id") or "").strip()
                    if not question or not question_id:
                        continue
                    turn_id = (item.get("turn_id") or "").strip()
                    images_value = item.get("user_answer_images")
                    images_json = (
                        _json_dumps(images_value) if isinstance(images_value, list) else None
                    )
                    await cur.execute(
                        """SELECT id FROM dt_notebook_entries
                           WHERE user_id=%s AND session_id=%s AND turn_id=%s AND question_id=%s""",
                        (user_id, session_id, turn_id, question_id),
                    )
                    existing = await cur.fetchone()
                    if existing:
                        set_clause = "user_answer=%s, is_correct=%s, updated_at=%s"
                        params: list[Any] = [
                            item.get("user_answer") or "",
                            1 if item.get("is_correct") else 0,
                            now,
                        ]
                        if images_json is not None:
                            set_clause += ", user_answer_images_json=%s"
                            params.append(images_json)
                        params.append(existing["id"])
                        await cur.execute(
                            f"UPDATE dt_notebook_entries SET {set_clause} WHERE id=%s", params
                        )
                    else:
                        await cur.execute(
                            """INSERT INTO dt_notebook_entries (
                                user_id, session_id, turn_id, question_id, question, question_type,
                                options_json, correct_answer, explanation, difficulty,
                                user_answer, user_answer_images_json, is_correct, bookmarked,
                                followup_session_id, created_at, updated_at
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s)""",
                            (
                                user_id,
                                session_id,
                                turn_id,
                                question_id,
                                question,
                                item.get("question_type") or "",
                                _json_dumps(item.get("options") or {}),
                                item.get("correct_answer") or "",
                                item.get("explanation") or "",
                                item.get("difficulty") or "",
                                item.get("user_answer") or "",
                                images_json or "[]",
                                1 if item.get("is_correct") else 0,
                                item.get("followup_session_id") or "",
                                now,
                                now,
                            ),
                        )
                    upserted += 1
            await conn.commit()
        return upserted

    @staticmethod
    def _serialize_notebook_entry(row: dict[str, Any]) -> dict[str, Any]:
        images: list[dict[str, Any]] = []
        raw_images = _json_loads(row.get("user_answer_images_json"), [])
        if isinstance(raw_images, list):
            images = [r for r in raw_images if isinstance(r, dict)]
        return {
            "id": int(row["id"]),
            "session_id": row.get("session_id") or "",
            "session_title": row.get("session_title") or "",
            "turn_id": row.get("turn_id") or "",
            "question_id": row.get("question_id") or "",
            "question": row.get("question") or "",
            "question_type": row.get("question_type") or "",
            "options": _json_loads(row.get("options_json"), {}),
            "correct_answer": row.get("correct_answer") or "",
            "explanation": row.get("explanation") or "",
            "difficulty": row.get("difficulty") or "",
            "user_answer": row.get("user_answer") or "",
            "user_answer_images": images,
            "is_correct": bool(row.get("is_correct")),
            "bookmarked": bool(row.get("bookmarked")),
            "followup_session_id": row.get("followup_session_id") or "",
            "ai_judgment": row.get("ai_judgment") or "",
            "image_refs": _json_loads(row.get("image_refs"), []),
            "knowledge_point": row.get("knowledge_point") or "",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def list_notebook_entries(
        self,
        category_id: int | None = None,
        bookmarked: bool | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        uncategorized: bool = False,
        search: str = "",
        sort: str = "newest",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        conditions: list[str] = ["n.user_id = %s"]
        params: list[Any] = [user_id]
        if category_id is not None:
            conditions.append("EXISTS (SELECT 1 FROM dt_notebook_entry_categories ec WHERE ec.entry_id = n.id AND ec.category_id = %s)")
            params.append(category_id)
        elif uncategorized:
            conditions.append("NOT EXISTS (SELECT 1 FROM dt_notebook_entry_categories ec WHERE ec.entry_id = n.id)")
        if bookmarked is not None:
            conditions.append("n.bookmarked = %s")
            params.append(1 if bookmarked else 0)
        if is_correct is not None:
            conditions.append("n.is_correct = %s")
            params.append(1 if is_correct else 0)
        if session_id:
            conditions.append("n.session_id = %s")
            params.append(session_id)
        if search:
            needle = f"%{search}%"
            conditions.append("(n.question LIKE %s OR n.user_answer LIKE %s OR n.correct_answer LIKE %s OR n.explanation LIKE %s)")
            params.extend([needle] * 4)
        where = " WHERE " + " AND ".join(conditions)
        order = "ASC" if sort == "oldest" else "DESC"
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""SELECT COUNT(*) AS cnt FROM dt_notebook_entries n{where}""", params
                )
                total_row = await cur.fetchone()
                total = int(total_row["cnt"]) if total_row else 0
                await cur.execute(
                    f"""SELECT n.*, COALESCE(s.title, '') AS session_title
                        FROM dt_notebook_entries n
                        LEFT JOIN dt_sessions s ON s.id = n.session_id
                        {where} ORDER BY n.created_at {order}, n.id {order} LIMIT %s OFFSET %s""",
                    params + [int(limit), int(offset)],
                )
                rows = await cur.fetchall()
                items = [self._serialize_notebook_entry(r) for r in rows]
                ids = [int(i["id"]) for i in items]
                categories = await self._load_categories_for(conn, ids, user_id)
        for item in items:
            item["categories"] = categories.get(int(item["id"]), [])
        return {"items": items, "total": total}

    async def _load_categories_for(
        self, conn, entry_ids: list[int], user_id: str
    ) -> dict[int, list[dict[str, Any]]]:
        if not entry_ids:
            return {}
        placeholders = ",".join(["%s"] * len(entry_ids))
        async with conn.cursor() as cur:
            await cur.execute(
                f"""SELECT ec.entry_id, c.id, c.name
                    FROM dt_notebook_entry_categories ec
                    INNER JOIN dt_notebook_categories c ON c.id = ec.category_id
                    WHERE ec.entry_id IN ({placeholders}) ORDER BY c.name""",
                entry_ids,
            )
            rows = await cur.fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["entry_id"]), []).append(
                {"id": row["id"], "name": row["name"]}
            )
        return grouped

    async def question_bank_stats(self) -> dict[str, int]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT
                        COUNT(*) AS total,
                        COALESCE(SUM(is_correct = 0), 0) AS wrong,
                        COALESCE(SUM(bookmarked = 1), 0) AS bookmarked,
                        (SELECT COUNT(*) FROM dt_notebook_entries n
                         WHERE n.user_id = %s AND NOT EXISTS (
                           SELECT 1 FROM dt_notebook_entry_categories ec WHERE ec.entry_id = n.id
                         )) AS uncategorized
                      FROM dt_notebook_entries WHERE user_id = %s""",
                    (user_id, user_id),
                )
                row = await cur.fetchone()
        return {
            "total": int(row["total"] or 0),
            "wrong": int(row["wrong"] or 0),
            "bookmarked": int(row["bookmarked"] or 0),
            "uncategorized": int(row["uncategorized"] or 0),
        }

    async def has_question_bank_entries(self) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM dt_notebook_entries WHERE user_id=%s LIMIT 1", (user_id,)
                )
                return await cur.fetchone() is not None

    async def get_notebook_entry(self, entry_id: int) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT n.*, COALESCE(s.title, '') AS session_title
                       FROM dt_notebook_entries n
                       LEFT JOIN dt_sessions s ON s.id = n.session_id
                       WHERE n.id=%s AND n.user_id=%s""",
                    (entry_id, user_id),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                item = self._serialize_notebook_entry(row)
                item["categories"] = (await self._load_categories_for(conn, [entry_id], user_id)).get(entry_id, [])
                return item

    async def find_notebook_entry(
        self,
        session_id: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if session_id:
                    await cur.execute(
                        """SELECT * FROM dt_notebook_entries
                           WHERE user_id=%s AND session_id=%s AND question_id=%s
                             AND (%s = '' OR turn_id = %s) LIMIT 1""",
                        (user_id, session_id, question_id, turn_id or "", turn_id or ""),
                    )
                else:
                    await cur.execute(
                        "SELECT * FROM dt_notebook_entries WHERE user_id=%s AND question_id=%s LIMIT 1",
                        (user_id, question_id),
                    )
                row = await cur.fetchone()
                return self._serialize_notebook_entry(row) if row else None

    async def update_notebook_entry(self, entry_id: int, updates: dict[str, Any]) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        allowed = {
            "user_answer", "user_answer_images_json", "is_correct", "bookmarked",
            "ai_judgment", "explanation", "knowledge_point",
        }
        cols = {k: v for k, v in updates.items() if k in allowed}
        if not cols:
            return False
        cols["updated_at"] = time.time()
        set_sql = ", ".join(f"{k}=%s" for k in cols)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE dt_notebook_entries SET {set_sql} WHERE id=%s AND user_id=%s",
                    list(cols.values()) + [entry_id, user_id],
                )
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM dt_notebook_entry_categories WHERE entry_id=%s", (entry_id,)
                )
                await cur.execute(
                    "DELETE FROM dt_notebook_entries WHERE id=%s AND user_id=%s",
                    (entry_id, user_id),
                )
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    # ------------------------------------------------------------------
    # Question bank categories
    # ------------------------------------------------------------------

    async def create_category(self, name: str) -> dict[str, Any]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        now = time.time()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO dt_notebook_categories (user_id, name, created_at) VALUES (%s,%s,%s)",
                    (user_id, name, now),
                )
                category_id = cur.lastrowid
            await conn.commit()
        return {"id": category_id, "name": name}

    async def rename_category(self, category_id: int, name: str) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE dt_notebook_categories SET name=%s WHERE id=%s AND user_id=%s",
                    (name, category_id, user_id),
                )
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    async def delete_category(self, category_id: int) -> bool:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM dt_notebook_entry_categories WHERE category_id=%s", (category_id,)
                )
                await cur.execute(
                    "DELETE FROM dt_notebook_categories WHERE id=%s AND user_id=%s",
                    (category_id, user_id),
                )
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    async def list_categories(self) -> list[dict[str, Any]]:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT c.id, c.name, COUNT(ec.entry_id) AS entry_count
                       FROM dt_notebook_categories c
                       LEFT JOIN dt_notebook_entry_categories ec ON ec.category_id = c.id
                       WHERE c.user_id = %s
                       GROUP BY c.id, c.name ORDER BY c.name""",
                    (user_id,),
                )
                rows = await cur.fetchall()
        return [
            {"id": int(r["id"]), "name": r["name"], "entry_count": int(r["entry_count"] or 0)}
            for r in rows
        ]

    async def find_category_by_name(self, name: str) -> dict[str, Any] | None:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM dt_notebook_categories WHERE user_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
                    (user_id, name),
                )
                row = await cur.fetchone()
                return {"id": int(row["id"]), "name": row["name"]} if row else None

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        return await self.link_entries_to_category([entry_id], category_id, link=True) > 0

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        pool = await get_mysql_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM dt_notebook_entry_categories WHERE entry_id=%s AND category_id=%s",
                    (entry_id, category_id),
                )
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    async def link_entries_to_category(
        self, entry_ids: list[int], category_id: int, *, link: bool = True
    ) -> int:
        pool = await get_mysql_pool()
        user_id = _current_user_id()
        changed = 0
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Only operate on the user's own entries.
                ph = ",".join(["%s"] * len(entry_ids))
                await cur.execute(
                    f"SELECT id FROM dt_notebook_entries WHERE user_id=%s AND id IN ({ph})",
                    [user_id, *entry_ids],
                )
                owned = {int(r["id"]) for r in await cur.fetchall()}
                for entry_id in owned:
                    if link:
                        await cur.execute(
                            "INSERT IGNORE INTO dt_notebook_entry_categories (entry_id, category_id) VALUES (%s,%s)",
                            (entry_id, category_id),
                        )
                        changed += cur.rowcount
                    else:
                        await cur.execute(
                            "DELETE FROM dt_notebook_entry_categories WHERE entry_id=%s AND category_id=%s",
                            (entry_id, category_id),
                        )
                        changed += cur.rowcount
            await conn.commit()
        return changed


# ---------------------------------------------------------------------------
# Public factory (matches sqlite_store.get_sqlite_session_store naming)
# ---------------------------------------------------------------------------

_mysql_store_instance: "MySQLSessionStore | None" = None


def get_mysql_session_store() -> MySQLSessionStore:
    """Return a process-wide singleton MySQLSessionStore.

    Must be a singleton: TurnRuntimeManager keys its instances by
    ``id(store)`` (MySQL has no ``db_path``), so returning a fresh instance on
    every call yields a different manager each time — the turn's execution and
    the frontend's subscription would live on different managers, breaking
    live event delivery and mis-failing running turns as orphans.
    """
    global _mysql_store_instance
    if _mysql_store_instance is None:
        _mysql_store_instance = MySQLSessionStore()
    return _mysql_store_instance
