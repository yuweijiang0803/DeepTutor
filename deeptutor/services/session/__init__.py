"""
Modified from DeepTutor (Apache-2.0, https://github.com/HKUDS/DeepTutor).
Original copyright: 2025 Data Intelligence Lab, The University of Hong Kong.
This file was modified by yuweijiang0803 for the K12 teaching-engine fork:
get_session_store() now selects MySQLSessionStore when MYSQL_HOST is set.
See git history and NOTICE for details.

Session Management Module
=========================

Provides unified session management for all agent modules.

Usage:
    from deeptutor.services.session import BaseSessionManager

    class MySessionManager(BaseSessionManager):
        def __init__(self):
            super().__init__("my_module")

        def _get_session_id_prefix(self) -> str:
            return "my_"

        def _get_default_title(self) -> str:
            return "New My Session"

        # ... implement other abstract methods
"""

from .base_session_manager import BaseSessionManager
from .protocol import SessionStoreProtocol
from .sqlite_store import (
    SQLiteSessionStore,
    get_sqlite_session_store,
    make_imported_session_id,
)
from .turn_runtime import TurnRuntimeManager, get_turn_runtime_manager


def get_session_store() -> SessionStoreProtocol:
    """
    Return the active session store backend.

    Mode is chosen by the storage configuration:

    - ``mysql`` (MySQL configured, web/server deployment): MySQLSessionStore.
    - ``dual`` (MySQL configured + ``dual: true``, PC sync enabled): a
      DualSessionStore — reads from local SQLite, writes to both.
    - ``local`` (no MySQL, PC default): SQLiteSessionStore.

    When integrations.pocketbase_url is configured, returns a
    PocketBaseSessionStore instead.
    """
    from deeptutor.services.pocketbase_client import is_pocketbase_enabled

    if is_pocketbase_enabled():
        from .pocketbase_store import PocketBaseSessionStore

        return PocketBaseSessionStore()
    from deeptutor.services.session.mysql_store import storage_mode

    mode = storage_mode()
    if mode == "dual":
        from .dual_store import get_dual_session_store

        return get_dual_session_store()
    if mode == "mysql":
        from .mysql_store import get_mysql_session_store

        return get_mysql_session_store()
    return get_sqlite_session_store()


__all__ = [
    "BaseSessionManager",
    "SessionStoreProtocol",
    "SQLiteSessionStore",
    "TurnRuntimeManager",
    "get_session_store",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
    "make_imported_session_id",
]
