"""Local ↔ server data migration for the LOCAL_MODE dual-mode feature.

Two storage modes share one codebase:

- **local mode** (default): conversations, question bank and mastery paths live
  in the per-user SQLite store and local files — open-source behaviour,
  no login required.
- **sync mode**: those three payload classes are copied to the shared MySQL
  store (``mixly`` database, ``dt_*`` tables) under the logged-in user's id,
  after which every read/write goes through MySQL.

Migration is a one-shot copy (per record, last-write-wins by id/unique key).
Conversation tables whose ids are globally auto-incremented on the server
(messages, turn_events) are remapped while copying; session/turn ids are UUID
strings and are preserved, so cross-references (parent_message_id,
summary_up_to_msg_id) are rewritten through the id map.

The sync service deliberately instantiates ``SQLiteSessionStore`` /
``MySQLSessionStore`` / ``LearningStore`` / ``MySQLLearningStore`` directly
instead of the ``get_*_store()`` factories, because the factory switches on
``mysql_configured()`` and a migration runs exactly at the moment the mode
flips — both backends must be addressable at once.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from deeptutor.services.session.mysql_store import get_mysql_pool
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@dataclass
class MigrationReport:
    """Per-payload-class counts from a migration run."""

    sessions: int = 0
    turns: int = 0
    messages: int = 0
    events: int = 0
    notebook_entries: int = 0
    mastery_paths: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": self.sessions,
            "turns": self.turns,
            "messages": self.messages,
            "events": self.events,
            "notebook_entries": self.notebook_entries,
            "mastery_paths": self.mastery_paths,
        }


def _sqlite_conn() -> sqlite3.Connection:
    """Read-only connection to the per-user SQLite history database."""
    store = SQLiteSessionStore()
    conn = sqlite3.connect(f"file:{store.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_conn_rw() -> sqlite3.Connection:
    """Read-write connection to the per-user SQLite history database."""
    store = SQLiteSessionStore()
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Server schema (idempotent) — a fresh PC client's MySQL may lack the
# question-bank / mastery tables, which historically were created by hand.
# ---------------------------------------------------------------------------

_SERVER_SCHEMA = """
CREATE TABLE IF NOT EXISTS dt_notebook_entries (
  id                      BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id                 VARCHAR(64)  NOT NULL,
  session_id              VARCHAR(64)  NOT NULL,
  turn_id                 VARCHAR(64)  NOT NULL DEFAULT '',
  question_id             VARCHAR(64)  NOT NULL,
  question                MEDIUMTEXT   NOT NULL,
  question_type           VARCHAR(16)  NOT NULL DEFAULT '',
  options_json            MEDIUMTEXT,
  correct_answer          MEDIUMTEXT,
  explanation             MEDIUMTEXT,
  difficulty              VARCHAR(16)  NOT NULL DEFAULT '',
  user_answer             MEDIUMTEXT,
  user_answer_images_json MEDIUMTEXT,
  is_correct              TINYINT      NOT NULL DEFAULT 0,
  bookmarked              TINYINT      NOT NULL DEFAULT 0,
  ai_judgment             MEDIUMTEXT,
  image_refs              MEDIUMTEXT,
  knowledge_point         VARCHAR(255) NOT NULL DEFAULT '',
  created_at              DOUBLE       NOT NULL,
  updated_at              DOUBLE       NOT NULL,
  KEY idx_entries_user (user_id, updated_at),
  KEY idx_entries_kp (knowledge_point)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_paths (
  path_id     VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id     VARCHAR(64)  NOT NULL,
  state_json  MEDIUMTEXT   NOT NULL,
  revision    BIGINT       NOT NULL,
  created_at  DOUBLE       NOT NULL,
  updated_at  DOUBLE       NOT NULL,
  KEY idx_path_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_path_sessions (
  path_id      VARCHAR(64) NOT NULL,
  session_id   VARCHAR(64) NOT NULL,
  owns_path    TINYINT     NOT NULL DEFAULT 0,
  created_at   DOUBLE      NOT NULL,
  last_seen_at DOUBLE      NOT NULL,
  PRIMARY KEY (path_id, session_id),
  KEY idx_ms_session (session_id, last_seen_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_interactions (
  interaction_id VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id        VARCHAR(64)  NOT NULL,
  path_id        VARCHAR(64)  NOT NULL,
  status         VARCHAR(16)  NOT NULL,
  question_json  MEDIUMTEXT   NOT NULL,
  session_id     VARCHAR(64)  NOT NULL DEFAULT '',
  turn_id        VARCHAR(64)  NOT NULL DEFAULT '',
  user_answer    MEDIUMTEXT   NOT NULL,
  result_json    MEDIUMTEXT   NOT NULL,
  created_at     DOUBLE       NOT NULL,
  updated_at     DOUBLE       NOT NULL,
  KEY idx_mi_path (path_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_events (
  id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id      VARCHAR(64)  NOT NULL,
  path_id      VARCHAR(64)  NOT NULL,
  revision     BIGINT       NOT NULL,
  event_type   VARCHAR(32)  NOT NULL,
  payload_json MEDIUMTEXT   NOT NULL,
  session_id   VARCHAR(64)  NOT NULL DEFAULT '',
  turn_id      VARCHAR(64)  NOT NULL DEFAULT '',
  created_at   DOUBLE       NOT NULL,
  KEY idx_me_path (path_id, revision, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_path_leases (
  path_id     VARCHAR(64) NOT NULL PRIMARY KEY,
  session_id  VARCHAR(64) NOT NULL,
  turn_id     VARCHAR(64) NOT NULL UNIQUE,
  acquired_at DOUBLE      NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


async def ensure_server_schema() -> None:
    """Create the question-bank / mastery tables if they do not exist yet."""
    import warnings

    pool = await get_mysql_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for stmt in _SERVER_SCHEMA.split(";"):
                if stmt.strip():
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        await cur.execute(stmt)
        await conn.commit()


# ---------------------------------------------------------------------------
# Conversations (sessions / turns / messages / turn_events) — db-layer copy
# ---------------------------------------------------------------------------


async def _copy_conversations_to_server(report: MigrationReport) -> None:
    """Copy local SQLite conversations into the shared MySQL store.

    session/turn ids are UUID strings and preserved; message ids are
    auto-incremented on the server, so the copy remaps them and rewrites
    ``parent_message_id`` / ``summary_up_to_msg_id`` through the map.
    """
    from deeptutor.services.session.mysql_store import _current_user_id

    user_id = _current_user_id()
    local = _sqlite_conn()
    pool = await get_mysql_pool()

    sessions = local.execute("SELECT * FROM sessions ORDER BY id").fetchall()
    for s in sessions:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT IGNORE INTO dt_sessions (
                        id, user_id, title, created_at, updated_at,
                        compressed_summary, summary_up_to_msg_id, preferences_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        s["id"],
                        user_id,
                        s["title"],
                        s["created_at"],
                        s["updated_at"],
                        s["compressed_summary"] or "",
                        int(s["summary_up_to_msg_id"] or 0),
                        s["preferences_json"] or "{}",
                    ),
                )
                # turns
                turns = local.execute(
                    "SELECT * FROM turns WHERE session_id = ? ORDER BY id", (s["id"],)
                ).fetchall()
                for t in turns:
                    await cur.execute(
                        """
                        INSERT IGNORE INTO dt_turns (
                            id, session_id, user_id, capability, status, error,
                            created_at, updated_at, finished_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            t["id"],
                            s["id"],
                            user_id,
                            t["capability"] or "",
                            t["status"] or "running",
                            t["error"] or "",
                            t["created_at"],
                            t["updated_at"],
                            t["finished_at"],
                        ),
                    )
                    # turn events (ids re-assigned; unique key turn_id+seq)
                    events = local.execute(
                        "SELECT * FROM turn_events WHERE turn_id = ? ORDER BY seq",
                        (t["id"],),
                    ).fetchall()
                    for e in events:
                        await cur.execute(
                            """
                            INSERT IGNORE INTO dt_turn_events (
                                turn_id, seq, type, source, stage, content,
                                metadata_json, timestamp, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                t["id"],
                                int(e["seq"]),
                                e["type"] or "",
                                e["source"] or "",
                                e["stage"] or "",
                                e["content"] or "",
                                e["metadata_json"] or "",
                                e["timestamp"],
                                e["created_at"],
                            ),
                        )
                        report.events += 1
                # messages — remap ids so parent_message_id still points at
                # the right row after the server reassigns ids.
                messages = local.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
                    (s["id"],),
                ).fetchall()
                id_map: dict[int, int] = {}
                for m in messages:
                    await cur.execute(
                        """
                        INSERT INTO dt_messages (
                            session_id, user_id, role, content, capability,
                            events_json, attachments_json, metadata_json,
                            created_at, parent_message_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            s["id"],
                            user_id,
                            m["role"] or "user",
                            m["content"] or "",
                            m["capability"] or "",
                            m["events_json"] or "",
                            m["attachments_json"] or "",
                            m["metadata_json"] or "{}",
                            m["created_at"],
                            id_map.get(int(m["parent_message_id"]))
                            if m["parent_message_id"] is not None
                            else None,
                        ),
                    )
                    id_map[int(m["id"])] = cur.lastrowid
                    report.messages += 1
                # summary_up_to_msg_id refers to a local message id — remap it.
                if s["summary_up_to_msg_id"]:
                    remapped = id_map.get(int(s["summary_up_to_msg_id"]))
                    if remapped is not None:
                        await cur.execute(
                            "UPDATE dt_sessions SET summary_up_to_msg_id = %s WHERE id = %s AND user_id = %s",
                            (remapped, s["id"], user_id),
                        )
            await conn.commit()
        report.sessions += 1
        report.turns += len(turns)


async def _copy_conversations_to_local(report: MigrationReport) -> None:
    """Copy the server-side conversations back into local SQLite."""
    from deeptutor.services.session.mysql_store import _current_user_id

    user_id = _current_user_id()
    pool = await get_mysql_pool()
    with _sqlite_conn_rw() as local:
        # Rebuild semantics: the local conversation tables are replaced from
        # the server copy (the server is authoritative while sync is on).
        for table in ("turn_events", "messages", "turns", "sessions"):
            local.execute(f"DELETE FROM {table}")
        local.commit()

        sessions: list[Any] = []
        turns: list[Any] = []
        messages: list[Any] = []
        events: list[Any] = []
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM dt_sessions WHERE user_id = %s ORDER BY id", (user_id,)
                )
                sessions = await cur.fetchall()
                for s in sessions:
                    await cur.execute(
                        "SELECT * FROM dt_turns WHERE session_id = %s ORDER BY id", (s["id"],)
                    )
                    turns.extend(await cur.fetchall())
                    await cur.execute(
                        "SELECT * FROM dt_messages WHERE session_id = %s ORDER BY id", (s["id"],)
                    )
                    messages.extend(await cur.fetchall())
                    await cur.execute(
                        "SELECT * FROM dt_turn_events WHERE turn_id IN (SELECT id FROM dt_turns WHERE session_id = %s) ORDER BY seq",
                        (s["id"],),
                    )
                    events.extend(await cur.fetchall())

        for s in sessions:
            local.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    id, title, created_at, updated_at,
                    compressed_summary, summary_up_to_msg_id, preferences_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s["id"],
                    s["title"],
                    s["created_at"],
                    s["updated_at"],
                    s["compressed_summary"] or "",
                    int(s["summary_up_to_msg_id"] or 0),
                    s["preferences_json"] or "{}",
                ),
            )
            report.sessions += 1
        id_map: dict[int, int] = {}
        for t in turns:
            local.execute(
                """
                INSERT OR REPLACE INTO turns (
                    id, session_id, capability, status, error,
                    created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t["id"],
                    t["session_id"],
                    t["capability"] or "",
                    t["status"] or "running",
                    t["error"] or "",
                    t["created_at"],
                    t["updated_at"],
                    t["finished_at"],
                ),
            )
            report.turns += 1
        for m in messages:
            cur = local.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, capability, events_json,
                    attachments_json, metadata_json, created_at, parent_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m["session_id"],
                    m["role"] or "user",
                    m["content"] or "",
                    m["capability"] or "",
                    m["events_json"] or "",
                    m["attachments_json"] or "",
                    m["metadata_json"] or "{}",
                    m["created_at"],
                    id_map.get(int(m["parent_message_id"]))
                    if m["parent_message_id"] is not None
                    else None,
                ),
            )
            id_map[int(m["id"])] = cur.lastrowid
            report.messages += 1
        # rewrite summary_up_to_msg_id for the local copies
        for s in sessions:
            if s["summary_up_to_msg_id"]:
                remapped = id_map.get(int(s["summary_up_to_msg_id"]))
                if remapped is not None:
                    local.execute(
                        "UPDATE sessions SET summary_up_to_msg_id = ? WHERE id = ?",
                        (remapped, s["id"]),
                    )
        for e in events:
            local.execute(
                """
                INSERT INTO turn_events (
                    turn_id, seq, type, source, stage, content,
                    metadata_json, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e["turn_id"],
                    int(e["seq"]),
                    e["type"] or "",
                    e["source"] or "",
                    e["stage"] or "",
                    e["content"] or "",
                    e["metadata_json"] or "",
                    e["timestamp"],
                    e["created_at"],
                ),
            )
            report.events += 1
        local.commit()


# ---------------------------------------------------------------------------
# Question bank (notebook_entries)
# ---------------------------------------------------------------------------


async def _copy_notebook_to_server(report: MigrationReport) -> None:
    """Copy local question-bank rows into ``dt_notebook_entries``."""
    from deeptutor.services.session.mysql_store import _current_user_id

    user_id = _current_user_id()
    local = _sqlite_conn()
    pool = await get_mysql_pool()

    rows = local.execute("SELECT * FROM notebook_entries ORDER BY id").fetchall()
    if not rows:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for r in rows:
                await cur.execute(
                    """
                    INSERT IGNORE INTO dt_notebook_entries (
                        user_id, session_id, turn_id, question_id, question,
                        question_type, options_json, correct_answer, explanation,
                        difficulty, user_answer, user_answer_images_json,
                        is_correct, bookmarked, followup_session_id,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        user_id,
                        r["session_id"],
                        r["turn_id"] or "",
                        r["question_id"],
                        r["question"],
                        r["question_type"] or "",
                        r["options_json"] or "{}",
                        r["correct_answer"] or "",
                        r["explanation"] or "",
                        r["difficulty"] or "",
                        r["user_answer"] or "",
                        r["user_answer_images_json"] or "[]",
                        1 if r["is_correct"] else 0,
                        1 if r["bookmarked"] else 0,
                        r["followup_session_id"] or "",
                        r["created_at"],
                        r["updated_at"],
                    ),
                )
                report.notebook_entries += 1
        await conn.commit()


async def _copy_notebook_to_local(report: MigrationReport) -> None:
    """Copy the server-side question bank back into local SQLite."""
    from deeptutor.services.session.mysql_store import _current_user_id

    user_id = _current_user_id()
    pool = await get_mysql_pool()
    rows: list[Any] = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM dt_notebook_entries WHERE user_id = %s ORDER BY id", (user_id,)
            )
            rows = await cur.fetchall()

    with _sqlite_conn_rw() as local:
        for r in rows:
            local.execute(
                """
                INSERT OR REPLACE INTO notebook_entries (
                    session_id, turn_id, question_id, question, question_type,
                    options_json, correct_answer, explanation, difficulty,
                    user_answer, user_answer_images_json, is_correct, bookmarked,
                    followup_session_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["session_id"],
                    r["turn_id"] or "",
                    r["question_id"],
                    r["question"],
                    r["question_type"] or "",
                    r["options_json"] or "{}",
                    r["correct_answer"] or "",
                    r["explanation"] or "",
                    r["difficulty"] or "",
                    r["user_answer"] or "",
                    r["user_answer_images_json"] or "[]",
                    1 if r["is_correct"] else 0,
                    1 if r["bookmarked"] else 0,
                    r["followup_session_id"] or "",
                    r["created_at"],
                    r["updated_at"],
                ),
            )
            report.notebook_entries += 1
        local.commit()


# ---------------------------------------------------------------------------
# Mastery paths — db-layer copy of the ``mastery_paths`` row
# ---------------------------------------------------------------------------


def _copy_mastery_to_server() -> int:
    """Copy local mastery paths into ``dt_mastery_paths`` (last-write-wins).

    Uses the same state_json serialization as the stores. A path missing on
    the server is inserted with revision 1; an existing one is overwritten
    only when the local copy is newer, so a re-migration never clobbers data
    the server has already accumulated.
    """
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.mysql_storage import MySQLLearningStore, _mysql_conn
    from deeptutor.services.session.mysql_store import _current_user_id

    local = LearningStore()
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        user_id = _current_user_id()
        now = time.time()
        count = 0
        for path_id in local.list_all():
            progress = local.load(path_id)
            if progress is None:
                continue
            cur.execute(
                "SELECT revision, updated_at FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                (path_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                payload = MySQLLearningStore._progress_payload(progress, 1, now)
                cur.execute(
                    """
                    INSERT IGNORE INTO dt_mastery_paths
                        (path_id, user_id, state_json, revision, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, %s, %s)
                    """,
                    (path_id, user_id, payload, progress.created_at, now),
                )
                if cur.rowcount:
                    count += 1
            elif progress.updated_at > row["updated_at"]:
                revision = int(row["revision"]) + 1
                payload = MySQLLearningStore._progress_payload(progress, revision, now)
                cur.execute(
                    """
                    UPDATE dt_mastery_paths
                    SET state_json=%s, revision=%s, updated_at=%s
                    WHERE path_id=%s AND user_id=%s
                    """,
                    (payload, revision, now, path_id, user_id),
                )
                count += 1
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _copy_mastery_to_local() -> int:
    """Copy server mastery paths back into the local SQLite store."""
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.mysql_storage import _mysql_conn
    from deeptutor.services.session.mysql_store import _current_user_id

    local = LearningStore()
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        user_id = _current_user_id()
        count = 0
        cur.execute(
            "SELECT path_id, state_json, revision, created_at, updated_at FROM dt_mastery_paths WHERE user_id=%s",
            (user_id,),
        )
        rows = cur.fetchall()
        for row in rows:
            progress = local.load(row["path_id"])
            if progress is not None and progress.updated_at > row["updated_at"]:
                # local is newer — never clobber it
                continue
            _write_mastery_local(local, row)
            count += 1
        return count
    finally:
        conn.close()


def _write_mastery_local(local, row: Any) -> None:
    """Persist one ``dt_mastery_paths`` row into the local SQLite store.

    A brand-new path goes through ``LearningStore.save`` (revision starts at
    0). An existing path is updated directly in its per-path SQLite file,
    bypassing the optimistic-revision check that ``save`` enforces — the
    caller has already decided this row wins (last-write-wins).
    """
    import json
    import sqlite3
    from pathlib import Path

    from deeptutor.learning.models import LearningProgress

    path_id = row["path_id"]
    # Validate the blob round-trips as a LearningProgress before touching disk.
    LearningProgress.model_validate(json.loads(row["state_json"]))

    existing = local.load(path_id)
    if existing is None:
        progress = LearningProgress.model_validate(json.loads(row["state_json"]))
        progress.version = 0
        progress.created_at = row["created_at"]
        progress.updated_at = row["updated_at"]
        local.save(progress)
        return

    db = Path(local.db_path)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE mastery_paths SET state_json=?, revision=?, updated_at=? WHERE path_id=?",
            (row["state_json"], int(row["revision"]), row["updated_at"], path_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def _clear_server_user_data() -> None:
    """Drop this user's migrated rows so a re-run of the migration is idempotent.

    ``dt_messages`` / ``dt_turn_events`` have no natural unique key beyond
    their auto-increment id, so a second run would otherwise duplicate every
    conversation row. Rebuild semantics: the local machine is authoritative
    for the three payload classes while sync mode is off.
    """
    from deeptutor.services.session.mysql_store import _current_user_id

    user_id = _current_user_id()
    pool = await get_mysql_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM dt_turn_events WHERE turn_id IN "
                "(SELECT id FROM dt_turns WHERE session_id IN "
                "(SELECT id FROM dt_sessions WHERE user_id=%s))",
                (user_id,),
            )
            await cur.execute(
                "DELETE FROM dt_messages WHERE session_id IN "
                "(SELECT id FROM dt_sessions WHERE user_id=%s)",
                (user_id,),
            )
            await cur.execute(
                "DELETE FROM dt_turns WHERE session_id IN "
                "(SELECT id FROM dt_sessions WHERE user_id=%s)",
                (user_id,),
            )
            await cur.execute(
                "DELETE FROM dt_sessions WHERE user_id=%s", (user_id,)
            )
            await cur.execute(
                "DELETE FROM dt_notebook_entries WHERE user_id=%s", (user_id,)
            )
            await cur.execute(
                "DELETE FROM dt_mastery_events WHERE path_id IN "
                "(SELECT path_id FROM dt_mastery_paths WHERE user_id=%s)",
                (user_id,),
            )
            await cur.execute(
                "DELETE FROM dt_mastery_interactions WHERE user_id=%s", (user_id,)
            )
            await cur.execute(
                "DELETE FROM dt_mastery_path_sessions WHERE path_id IN "
                "(SELECT path_id FROM dt_mastery_paths WHERE user_id=%s)",
                (user_id,),
            )
            await cur.execute(
                "DELETE FROM dt_mastery_paths WHERE user_id=%s", (user_id,)
            )
        await conn.commit()


async def migrate_local_to_server() -> MigrationReport:
    """One-shot copy: local SQLite → server MySQL (run right after enabling sync).

    Rebuild semantics: this user's previous server-side rows for the three
    payload classes are removed first, then the local data is written up, so
    re-runs are safe and the local machine is authoritative for sync-off
    data. Mastery paths are still merged last-write-wins per row as a
    safety net for paths the server created after the last sync.
    """
    await ensure_server_schema()
    await _clear_server_user_data()
    report = MigrationReport()
    await _copy_conversations_to_server(report)
    await _copy_notebook_to_server(report)
    report.mastery_paths = await asyncio.to_thread(_copy_mastery_to_server)
    return report


async def migrate_server_to_local() -> MigrationReport:
    """One-shot copy: server MySQL → local SQLite (run when disabling sync)."""
    report = MigrationReport()
    await _copy_conversations_to_local(report)
    await _copy_notebook_to_local(report)
    report.mastery_paths = await asyncio.to_thread(_copy_mastery_to_local)
    return report


__all__ = [
    "MigrationReport",
    "migrate_local_to_server",
    "migrate_server_to_local",
]
