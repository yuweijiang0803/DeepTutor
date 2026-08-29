"""Dual-mode session store: read local SQLite, write to both local + MySQL.

Used by the PC client when sync is enabled (``storage_mode() == "dual"``).
Reads always come from the local store (offline-capable, fast); writes are
applied to both the local SQLite store and the shared MySQL store, with the
remote copy best-effort (a failed remote write is logged, never raises).

The MySQL side manages its own auto-increment ids, so cross-references that
only make sense locally (message ``parent_message_id``, ``summary_up_to_msg_id``)
are left to MySQL's own chaining on the remote call — the remote copy is an
append-only mirror good enough for cross-device browsing and teacher reports.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.session.mysql_store import MySQLSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

logger = logging.getLogger(__name__)


class DualSessionStore:
    """Read local, write to both local and MySQL (remote best-effort)."""

    def __init__(self) -> None:
        self._local = SQLiteSessionStore()
        self._remote = MySQLSessionStore()

    # ------------------------------------------------------------------
    # Reads — proxied to the local store (authoritative on the PC).
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes not defined on this class (i.e. reads).
        local = self.__dict__.get("_local")
        if local is not None and hasattr(local, name):
            return getattr(local, name)
        raise AttributeError(name)

    # ------------------------------------------------------------------
    # Writes — local + remote, remote best-effort.
    # ------------------------------------------------------------------

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        result = await self._local.create_session(title=title, session_id=session_id)
        try:
            await self._remote.create_session(title=title, session_id=session_id)
        except Exception as exc:
            logger.warning("dual: create_session sync failed: %s", exc)
        return result

    async def ensure_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await self._local.ensure_session(*args, **kwargs)
        try:
            await self._remote.ensure_session(*args, **kwargs)
        except Exception as exc:
            logger.warning("dual: ensure_session sync failed: %s", exc)
        return result

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        result = await self._local.create_turn(session_id, capability)
        try:
            # Mirror with the SAME turn id so streamed events written later
            # (append_turn_event) land on the matching server-side turn.
            await self._remote.create_turn(
                session_id, capability, turn_id=result["turn_id"]
            )
        except Exception as exc:
            logger.warning("dual: create_turn sync failed: %s", exc)
        return result

    async def update_turn_status(
        self, turn_id: str, status: str, error: str = ""
    ) -> bool:
        result = await self._local.update_turn_status(turn_id, status, error)
        try:
            await self._remote.update_turn_status(turn_id, status, error)
        except Exception as exc:
            logger.warning("dual: update_turn_status sync failed: %s", exc)
        return result

    async def append_turn_event(
        self, turn_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self._local.append_turn_event(turn_id, event)
        try:
            await self._remote.append_turn_event(turn_id, event)
        except Exception as exc:
            logger.warning("dual: append_turn_event sync failed: %s", exc)
        return result

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result = await self._local.append_turn_events(turn_id, events)
        try:
            await self._remote.append_turn_events(turn_id, events)
        except Exception as exc:
            logger.warning("dual: append_turn_events sync failed: %s", exc)
        return result

    async def update_session_title(self, session_id: str, title: str) -> bool:
        result = await self._local.update_session_title(session_id, title)
        try:
            await self._remote.update_session_title(session_id, title)
        except Exception as exc:
            logger.warning("dual: update_session_title sync failed: %s", exc)
        return result

    async def delete_session(self, session_id: str) -> bool:
        result = await self._local.delete_session(session_id)
        try:
            await self._remote.delete_session(session_id)
        except Exception as exc:
            logger.warning("dual: delete_session sync failed: %s", exc)
        return result

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None | object = None,
    ) -> int | str:
        result = await self._local.add_message(
            session_id,
            role,
            content,
            capability,
            events,
            attachments,
            metadata,
            parent_message_id,
        )
        try:
            # Let MySQL chain to its own last message instead of forwarding the
            # local rowid, which means nothing on the server.
            await self._remote.add_message(
                session_id, role, content, capability, events, attachments, metadata
            )
        except Exception as exc:
            logger.warning("dual: add_message sync failed: %s", exc)
        return result

    async def delete_message(self, message_id: int | str) -> bool:
        result = await self._local.delete_message(message_id)
        try:
            # Local rowids do not map to server ids; best-effort only.
            await self._remote.delete_message(message_id)
        except Exception as exc:
            logger.warning("dual: delete_message sync failed: %s", exc)
        return result

    async def update_summary(
        self, session_id: str, summary: str, up_to_msg_id: int
    ) -> bool:
        result = await self._local.update_summary(session_id, summary, up_to_msg_id)
        try:
            await self._remote.update_summary(session_id, summary, up_to_msg_id)
        except Exception as exc:
            logger.warning("dual: update_summary sync failed: %s", exc)
        return result

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        result = await self._local.update_session_preferences(session_id, preferences)
        try:
            await self._remote.update_session_preferences(session_id, preferences)
        except Exception as exc:
            logger.warning("dual: update_session_preferences sync failed: %s", exc)
        return result

    # ------------------------------------------------------------------
    # Question bank — writes double, reads proxied to local.
    # ------------------------------------------------------------------

    async def upsert_notebook_entries(
        self, session_id: str, items: list[dict[str, Any]]
    ) -> int:
        result = await self._local.upsert_notebook_entries(session_id, items)
        try:
            await self._remote.upsert_notebook_entries(session_id, items)
        except Exception as exc:
            logger.warning("dual: upsert_notebook_entries sync failed: %s", exc)
        return result

    async def update_notebook_entry(
        self, entry_id: int, updates: dict[str, Any]
    ) -> bool:
        result = await self._local.update_notebook_entry(entry_id, updates)
        try:
            await self._remote.update_notebook_entry(entry_id, updates)
        except Exception as exc:
            logger.warning("dual: update_notebook_entry sync failed: %s", exc)
        return result

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        result = await self._local.delete_notebook_entry(entry_id)
        try:
            await self._remote.delete_notebook_entry(entry_id)
        except Exception as exc:
            logger.warning("dual: delete_notebook_entry sync failed: %s", exc)
        return result

    async def create_category(self, name: str) -> dict[str, Any]:
        result = await self._local.create_category(name)
        try:
            await self._remote.create_category(name)
        except Exception as exc:
            logger.warning("dual: create_category sync failed: %s", exc)
        return result

    async def rename_category(self, category_id: int, name: str) -> bool:
        result = await self._local.rename_category(category_id, name)
        try:
            await self._remote.rename_category(category_id, name)
        except Exception as exc:
            logger.warning("dual: rename_category sync failed: %s", exc)
        return result


_dual_store: DualSessionStore | None = None


def get_dual_session_store() -> DualSessionStore:
    global _dual_store
    if _dual_store is None:
        _dual_store = DualSessionStore()
    return _dual_store


__all__ = ["DualSessionStore", "get_dual_session_store"]
