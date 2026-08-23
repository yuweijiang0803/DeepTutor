"""MySQL-backed LearningStore (mastery paths).

Mirrors :class:`deeptutor.learning.storage.LearningStore`'s public interface but
persists to the ``dt_mastery_*`` tables in the shared MySQL database, scoped by
``user_id``. Stays synchronous (pymysql) so call sites that use ``LearningStore``
directly do not need to change to async.

Transactional semantics are preserved:
  - each path's writes are serialized with ``SELECT ... FOR UPDATE`` (in place
    of SQLite's ``BEGIN IMMEDIATE``);
  - a revision CAS (``UPDATE ... WHERE revision = expected``) keeps optimistic
    concurrency;
  - every committed mutation appends a ``mastery_events`` row.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from deeptutor.learning.models import LearningProgress, MasteryEvent, MasteryInteraction
from deeptutor.learning.storage import (
    InteractionStatus,
    LearningConflictError,
    LearningStoreError,
    LearningTransaction,
    PathLeaseConflictError,
    _ACTIVE_INTERACTION_STATES,
)

_T = TypeVar("_T")

# user_id scoping: per-user tables carry it; a path belongs to its owner.
def _current_user_id() -> str:
    from deeptutor.services.session.mysql_store import _current_user_id as _muid

    return _muid()


def _mysql_conn():
    """Open a synchronous pymysql connection from the shared MySQL settings."""
    import pymysql

    from deeptutor.services.session.mysql_store import _mysql_settings

    cfg = _mysql_settings()
    return pymysql.connect(
        host=cfg.get("host") or "127.0.0.1",
        port=int(cfg.get("port") or 3306),
        user=cfg.get("user") or "root",
        password=cfg.get("password") or "",
        database=cfg.get("database") or "mixly",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


class _MySqlConnAdapter:
    """Minimal adapter so ``LearningTransaction`` (which calls ``conn.execute``)
    works against a pymysql connection. Translates the SQLite dialect the
    shared transaction code uses (``?`` placeholders, ``ON CONFLICT ... DO
    UPDATE``, table name ``mastery_interactions``) into MySQL."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @staticmethod
    def _mysqlify(sql: str) -> str:
        import re

        # Table name: the shared transaction code refers to the SQLite table.
        sql = re.sub(r"\bmastery_interactions\b", "dt_mastery_interactions", sql)
        # ON CONFLICT(...) DO UPDATE SET a = excluded.a -> ON DUPLICATE KEY UPDATE a = VALUES(a)
        def _on_conflict(match: re.Match) -> str:
            updates = re.sub(
                r"excluded\.([A-Za-z_]+)", r"VALUES(\1)", match.group(1)
            )
            return f"ON DUPLICATE KEY UPDATE {updates}"

        sql = re.sub(
            r"ON CONFLICT\([^)]*\)\s+DO UPDATE SET\s+(.*?)(?=\s*(?:WHERE\b|RETURNING\b|;|$))",
            _on_conflict,
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # ? placeholders -> MySQL %s. The shared SQL only uses ? for binding.
        sql = sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: tuple | None = None):
        from deeptutor.services.session.mysql_store import _current_user_id as _uid

        mysql_sql = self._mysqlify(sql)
        bind = tuple(params or ())
        # The shared LearningTransaction INSERT omits user_id (SQLite tables
        # are per-user); inject the current user's id into the MySQL row.
        if "INSERT INTO dt_mastery_interactions" in mysql_sql:
            mysql_sql = mysql_sql.replace(
                "INSERT INTO dt_mastery_interactions (",
                "INSERT INTO dt_mastery_interactions (user_id, ",
                1,
            )
            mysql_sql = mysql_sql.replace("VALUES (", "VALUES (%s, ", 1)
            bind = (_uid(),) + bind
        cur = self._conn.cursor()
        cur.execute(mysql_sql, bind)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


class MySQLLearningStore:
    """MySQL implementation of the mastery LearningStore interface."""

    def __init__(self, _root: Path | None = None) -> None:
        # root/db_path/legacy migration are SQLite-only; keep them for interface
        # parity but unused.
        self._root = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id(book_id: str) -> str:
        value = str(book_id or "")
        if not value or "/" in value or "\\" in value or ".." in value or ":" in value:
            raise ValueError(f"Invalid book_id: {book_id!r}")
        return value

    @staticmethod
    def _progress_from_row(row: dict[str, Any] | None) -> LearningProgress | None:
        if row is None:
            return None
        progress = LearningProgress.model_validate(json.loads(row["state_json"]))
        progress.version = int(row["revision"])
        return progress

    @staticmethod
    def _progress_payload(progress: LearningProgress, revision: int, updated_at: float) -> str:
        persisted = progress.model_copy(deep=True)
        persisted.version = revision
        persisted.updated_at = updated_at
        return json.dumps(persisted.model_dump(mode="json"), ensure_ascii=False)

    @staticmethod
    def _interaction_from_row(row: dict[str, Any] | None) -> MasteryInteraction | None:
        if row is None:
            return None
        return MasteryInteraction(
            interaction_id=row["interaction_id"],
            path_id=row["path_id"],
            question=json.loads(row["question_json"]),
            status=InteractionStatus(row["status"]),
            session_id=row["session_id"] or "",
            turn_id=row["turn_id"] or "",
            user_answer=row["user_answer"] or "",
            result=json.loads(row["result_json"] or "{}"),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _lease_from_row(row: dict[str, Any] | None):
        from deeptutor.learning.storage import MasteryPathLease

        if row is None:
            return None
        return MasteryPathLease(
            path_id=row["path_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            acquired_at=float(row["acquired_at"]),
        )

    # ------------------------------------------------------------------
    # Path CRUD
    # ------------------------------------------------------------------

    def load(self, book_id: str) -> LearningProgress | None:
        path_id = self._validate_id(book_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                    (path_id, _current_user_id()),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        return self._progress_from_row(row)

    def save(self, progress: LearningProgress) -> None:
        path_id = self._validate_id(progress.book_id)
        user_id = _current_user_id()
        now = time.time()
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT revision, created_at FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                (path_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                if int(progress.version) != 0:
                    raise LearningConflictError(path_id, int(progress.version), 0)
                revision = 1
                cur.execute(
                    """INSERT INTO dt_mastery_paths
                       (path_id, user_id, state_json, revision, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        path_id,
                        user_id,
                        self._progress_payload(progress, revision, now),
                        revision,
                        progress.created_at,
                        now,
                    ),
                )
                event_type = "path.created"
            else:
                actual = int(row["revision"])
                expected = int(progress.version)
                if actual != expected:
                    raise LearningConflictError(path_id, expected, actual)
                revision = actual + 1
                cur.execute(
                    """UPDATE dt_mastery_paths
                       SET state_json=%s, revision=%s, updated_at=%s
                       WHERE path_id=%s AND user_id=%s AND revision=%s""",
                    (
                        self._progress_payload(progress, revision, now),
                        revision,
                        now,
                        path_id,
                        user_id,
                        expected,
                    ),
                )
                if cur.rowcount != 1:
                    cur.execute(
                        "SELECT revision FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                        (path_id, user_id),
                    )
                    current = cur.fetchone()
                    raise LearningConflictError(
                        path_id, expected, int(current["revision"]) if current else 0
                    )
                event_type = "path.saved"
            cur.execute(
                """INSERT INTO dt_mastery_events
                   (user_id, path_id, revision, event_type, payload_json, created_at)
                   VALUES (%s,%s,%s,%s,'{}',%s)""",
                (user_id, path_id, revision, event_type, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        progress.version = revision
        progress.updated_at = now

    @contextmanager
    def transaction(self, book_id: str, *, create: bool = False) -> Iterator[LearningTransaction]:
        path_id = self._validate_id(book_id)
        user_id = _current_user_id()
        conn = _mysql_conn()
        adapter = _MySqlConnAdapter(conn)
        tx: LearningTransaction | None = None
        try:
            cur = conn.cursor()
            # Serialize writers for this path (analog of BEGIN IMMEDIATE).
            cur.execute(
                "SELECT * FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s FOR UPDATE",
                (path_id, user_id),
            )
            row = cur.fetchone()
            created = row is None
            if created:
                if not create:
                    raise KeyError(path_id)
                progress = LearningProgress(book_id=path_id)
                cur.execute(
                    """INSERT INTO dt_mastery_paths
                       (path_id, user_id, state_json, revision, created_at, updated_at)
                       VALUES (%s,%s,%s,0,%s,%s)""",
                    (
                        path_id,
                        user_id,
                        self._progress_payload(progress, 0, progress.updated_at),
                        progress.created_at,
                        progress.updated_at,
                    ),
                )
            else:
                progress = self._progress_from_row(row)
            tx = LearningTransaction(adapter, progress, created=created)
            yield tx
            if tx.changed:
                now = time.time()
                revision = tx.base_revision + 1
                cur.execute(
                    """UPDATE dt_mastery_paths
                       SET state_json=%s, revision=%s, updated_at=%s
                       WHERE path_id=%s AND user_id=%s AND revision=%s""",
                    (
                        self._progress_payload(tx.progress, revision, now),
                        revision,
                        now,
                        path_id,
                        user_id,
                        tx.base_revision,
                    ),
                )
                if cur.rowcount != 1:
                    cur.execute(
                        "SELECT revision FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                        (path_id, user_id),
                    )
                    current = cur.fetchone()
                    raise LearningConflictError(
                        path_id, tx.base_revision, int(current["revision"]) if current else 0
                    )
                for event_type, payload, session_id, turn_id in tx.events:
                    cur.execute(
                        """INSERT INTO dt_mastery_events
                           (user_id, path_id, revision, event_type, payload_json,
                            session_id, turn_id, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            user_id,
                            path_id,
                            revision,
                            event_type,
                            json.dumps(payload, ensure_ascii=False),
                            session_id,
                            turn_id,
                            now,
                        ),
                    )
                tx.progress.version = revision
                tx.progress.updated_at = now
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mutate(
        self,
        book_id: str,
        mutation: Callable[[LearningTransaction], _T],
        *,
        create: bool = False,
    ) -> tuple[LearningProgress, _T]:
        with self.transaction(book_id, create=create) as tx:
            result = mutation(tx)
        return tx.progress, result

    def delete(self, book_id: str) -> None:
        path_id = self._validate_id(book_id)
        user_id = _current_user_id()
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM dt_mastery_path_leases WHERE path_id=%s", (path_id,)
            )
            cur.execute(
                "DELETE FROM dt_mastery_interactions WHERE user_id=%s AND path_id=%s",
                (user_id, path_id),
            )
            cur.execute(
                "DELETE FROM dt_mastery_events WHERE user_id=%s AND path_id=%s",
                (user_id, path_id),
            )
            cur.execute(
                "DELETE FROM dt_mastery_path_sessions WHERE path_id=%s", (path_id,)
            )
            cur.execute(
                "DELETE FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                (path_id, user_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def exists(self, book_id: str) -> bool:
        path_id = self._validate_id(book_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                    (path_id, _current_user_id()),
                )
                return cur.fetchone() is not None
        finally:
            conn.close()

    def list_all(self) -> list[str]:
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT path_id FROM dt_mastery_paths WHERE user_id=%s",
                    (_current_user_id(),),
                )
                return [str(r["path_id"]) for r in cur.fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Path / session ownership
    # ------------------------------------------------------------------

    def bind_session(self, path_id: str, session_id: str, *, owns_path: bool = False) -> None:
        path_id = self._validate_id(path_id)
        user_id = _current_user_id()
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        now = time.time()
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s",
                (path_id, user_id),
            )
            if cur.fetchone() is None:
                progress = LearningProgress(book_id=path_id)
                cur.execute(
                    """INSERT INTO dt_mastery_paths
                       (path_id, user_id, state_json, revision, created_at, updated_at)
                       VALUES (%s,%s,%s,1,%s,%s)""",
                    (
                        path_id,
                        user_id,
                        json.dumps(progress.model_dump(mode="json"), ensure_ascii=False),
                        progress.created_at,
                        now,
                    ),
                )
                cur.execute(
                    """INSERT INTO dt_mastery_events
                       (user_id, path_id, revision, event_type, payload_json, created_at)
                       VALUES (%s,%s,1,'path.created','{}',%s)""",
                    (user_id, path_id, now),
                )
            cur.execute(
                """INSERT INTO dt_mastery_path_sessions
                   (path_id, session_id, owns_path, created_at, last_seen_at)
                   VALUES (%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     owns_path = GREATEST(owns_path, VALUES(owns_path)),
                     last_seen_at = VALUES(last_seen_at)""",
                (path_id, session_id, int(owns_path), now, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_session_ids(self, path_id: str) -> list[str]:
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT session_id FROM dt_mastery_path_sessions
                       WHERE path_id=%s ORDER BY last_seen_at DESC""",
                    (path_id,),
                )
                return [str(r["session_id"]) for r in cur.fetchall()]
        finally:
            conn.close()

    def list_paths_for_session(self, session_id: str) -> list[dict[str, Any]]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT path_id, owns_path, created_at, last_seen_at
                       FROM dt_mastery_path_sessions
                       WHERE session_id=%s ORDER BY last_seen_at DESC""",
                    (session_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def detach_session(self, session_id: str, *, delete_owned_orphans: bool = True) -> list[str]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        deleted_paths: list[str] = []
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT path_id, owns_path FROM dt_mastery_path_sessions WHERE session_id=%s",
                (session_id,),
            )
            rows = cur.fetchall()
            cur.execute(
                "DELETE FROM dt_mastery_path_leases WHERE session_id=%s", (session_id,)
            )
            cur.execute(
                "DELETE FROM dt_mastery_path_sessions WHERE session_id=%s", (session_id,)
            )
            if delete_owned_orphans:
                for row in rows:
                    if not bool(row["owns_path"]):
                        continue
                    path_id = str(row["path_id"])
                    cur.execute(
                        "SELECT 1 FROM dt_mastery_path_sessions WHERE path_id=%s LIMIT 1",
                        (path_id,),
                    )
                    if cur.fetchone() is None:
                        cur.execute(
                            "DELETE FROM dt_mastery_paths WHERE path_id=%s", (path_id,)
                        )
                        deleted_paths.append(path_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return deleted_paths

    # ------------------------------------------------------------------
    # Path leases
    # ------------------------------------------------------------------

    def get_path_lease(self, path_id: str):
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dt_mastery_path_leases WHERE path_id=%s", (path_id,)
                )
                return self._lease_from_row(cur.fetchone())
        finally:
            conn.close()

    def acquire_path_lease(
        self,
        path_id: str,
        session_id: str,
        turn_id: str,
        *,
        bind_session: bool = True,
    ):
        path_id = self._validate_id(path_id)
        session_id = str(session_id or "").strip()
        turn_id = str(turn_id or "").strip()
        if not session_id or not turn_id:
            raise ValueError("session_id and turn_id are required for a path lease")
        if bind_session:
            self.bind_session(path_id, session_id, owns_path=False)
        else:
            with self.transaction(path_id, create=True):
                pass
        now = time.time()
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM dt_mastery_path_leases WHERE path_id=%s FOR UPDATE",
                (path_id,),
            )
            existing = self._lease_from_row(cur.fetchone())
            if existing is not None and existing.turn_id != turn_id:
                raise PathLeaseConflictError(existing)
            cur.execute(
                """INSERT INTO dt_mastery_path_leases (path_id, session_id, turn_id, acquired_at)
                   VALUES (%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     session_id=VALUES(session_id), turn_id=VALUES(turn_id),
                     acquired_at=VALUES(acquired_at)""",
                (path_id, session_id, turn_id, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        from deeptutor.learning.storage import MasteryPathLease

        return MasteryPathLease(
            path_id=path_id, session_id=session_id, turn_id=turn_id, acquired_at=now
        )

    def release_leases_for_turn(self, turn_id: str) -> str:
        turn_id = str(turn_id or "").strip()
        if not turn_id:
            return ""
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT path_id FROM dt_mastery_path_leases WHERE turn_id=%s", (turn_id,)
            )
            row = cur.fetchone()
            if row is None:
                return ""
            cur.execute(
                "DELETE FROM dt_mastery_path_leases WHERE turn_id=%s", (turn_id,)
            )
            conn.commit()
            return str(row["path_id"])
        finally:
            conn.close()

    def release_path_lease(self, path_id: str, *, turn_id: str | None = None) -> bool:
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            if turn_id:
                cur.execute(
                    "DELETE FROM dt_mastery_path_leases WHERE path_id=%s AND turn_id=%s",
                    (path_id, str(turn_id)),
                )
            else:
                cur.execute(
                    "DELETE FROM dt_mastery_path_leases WHERE path_id=%s", (path_id,)
                )
            conn.commit()
            return bool(cur.rowcount)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Interactions / events
    # ------------------------------------------------------------------

    def get_interaction(self, path_id: str, interaction_id: str) -> MasteryInteraction | None:
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM dt_mastery_interactions
                       WHERE path_id=%s AND interaction_id=%s""",
                    (path_id, str(interaction_id)),
                )
                return self._interaction_from_row(cur.fetchone())
        finally:
            conn.close()

    def get_active_interaction(self, path_id: str) -> MasteryInteraction | None:
        path_id = self._validate_id(path_id)
        placeholders = ",".join(["%s"] * len(_ACTIVE_INTERACTION_STATES))
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT * FROM dt_mastery_interactions
                        WHERE path_id=%s AND status IN ({placeholders})
                        ORDER BY created_at DESC LIMIT 1""",
                    (path_id, *_ACTIVE_INTERACTION_STATES),
                )
                return self._interaction_from_row(cur.fetchone())
        finally:
            conn.close()

    def list_interactions(self, path_id: str, *, limit: int = 200) -> list[MasteryInteraction]:
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM dt_mastery_interactions
                       WHERE path_id=%s
                       ORDER BY created_at DESC, interaction_id DESC LIMIT %s""",
                    (path_id, max(1, int(limit))),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [i for i in (self._interaction_from_row(r) for r in rows) if i is not None]

    def list_events(self, path_id: str, *, after_revision: int = 0) -> list[MasteryEvent]:
        path_id = self._validate_id(path_id)
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM dt_mastery_events
                       WHERE path_id=%s AND revision>%s
                       ORDER BY revision ASC, id ASC""",
                    (path_id, max(0, int(after_revision))),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            MasteryEvent(
                id=int(r["id"]),
                path_id=r["path_id"],
                revision=int(r["revision"]),
                event_type=r["event_type"],
                payload=json.loads(r["payload_json"] or "{}"),
                session_id=r["session_id"] or "",
                turn_id=r["turn_id"] or "",
                created_at=float(r["created_at"]),
            )
            for r in rows
        ]


def get_learning_store() -> MySQLLearningStore | Any:
    """Return the MySQL LearningStore when MySQL is configured, else the SQLite one."""
    from deeptutor.services.session.mysql_store import mysql_configured

    if mysql_configured():
        return MySQLLearningStore()
    from deeptutor.learning.storage import LearningStore

    return LearningStore()
