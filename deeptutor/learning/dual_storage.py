"""Dual-mode learning store: read local SQLite, write to both local + MySQL.

Mirrors ``DualSessionStore`` for mastery paths. The local store is
authoritative for reads; ``save`` applies the write locally and then mirrors
the path's ``state_json`` to ``dt_mastery_paths`` best-effort, so the remote
copy stays current enough for cross-device and teacher-facing views without
the full interaction-level transaction sync.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

from deeptutor.learning.storage import LearningStore

logger = logging.getLogger(__name__)


class DualLearningStore:
    """Read local, write to both local and MySQL (remote best-effort)."""

    def __init__(self) -> None:
        self._local = LearningStore()

    def __getattr__(self, name: str) -> Any:
        # Reads (load / exists / list_* / get_* / transaction) proxy to local.
        local = self.__dict__.get("_local")
        if local is not None and hasattr(local, name):
            return getattr(local, name)
        raise AttributeError(name)

    def save(self, progress) -> None:
        self._local.save(progress)
        try:
            _upsert_mastery_path(progress)
        except Exception as exc:
            logger.warning("dual: mastery path sync failed (%s): %s", progress.book_id, exc)

    def delete(self, book_id: str) -> None:
        self._local.delete(book_id)
        try:
            _delete_mastery_path(book_id)
        except Exception as exc:
            logger.warning("dual: mastery path delete sync failed (%s): %s", book_id, exc)


def _upsert_mastery_path(progress) -> None:
    """Mirror one path's state_json to ``dt_mastery_paths`` (last-write-wins)."""
    from deeptutor.learning.mysql_storage import MySQLLearningStore, _mysql_conn
    from deeptutor.services.session.mysql_store import _current_user_id

    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        user_id = _current_user_id()
        now = time.time()
        path_id = progress.book_id
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
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_mastery_path(path_id: str) -> None:
    """Remove the path (and its child rows) from the MySQL store."""
    from deeptutor.learning.mysql_storage import _mysql_conn
    from deeptutor.services.session.mysql_store import _current_user_id

    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        user_id = _current_user_id()
        cur.execute(
            "DELETE FROM dt_mastery_events WHERE path_id IN "
            "(SELECT path_id FROM dt_mastery_paths WHERE path_id=%s AND user_id=%s)",
            (path_id, user_id),
        )
        cur.execute(
            "DELETE FROM dt_mastery_interactions WHERE path_id=%s AND user_id=%s",
            (path_id, user_id),
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


_dual_learning_store: DualLearningStore | None = None


def get_dual_learning_store() -> DualLearningStore:
    global _dual_learning_store
    if _dual_learning_store is None:
        _dual_learning_store = DualLearningStore()
    return _dual_learning_store


__all__ = ["DualLearningStore", "get_dual_learning_store"]
