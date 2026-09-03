"""Subject-pack service — global textbook-aligned content tree.

A subject pack is global pre-set content shared by every learner:

    Subject (dt_subject) → Module / chapter → KnowledgePoint → Question

Backends, in priority order:

1. **MySQL** (``SubjectMySQLStore``) — the real home of the ``dt_subject*``
   tables.  Used whenever the shared MySQL settings carry a host and the server
   answers.  On first use the tables are created (``SUBJECT_SCHEMA_SQL``) and,
   if empty, auto-seeded from the built-in presets.
2. **Presets JSON** — fallback when MySQL is unreachable/not configured, so the
   read path still works on a fresh laptop or in tests.

Every node carries a stable semantic id (``math-rjb-7a-u1-k2``) that doubles as
the mastery engine's ``LearningModule.id`` / ``KnowledgePoint.id``, so content
seeded here maps onto mastery paths with zero translation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.subject_pack.models import (
    Subject,
    SubjectKnowledgePoint,
    SubjectModule,
    SubjectQuestion,
)

logger = logging.getLogger(__name__)

PRESETS_DIR = Path(__file__).resolve().parent / "presets"


class SubjectNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Presets JSON backend (fallback read-only source + seed material)
# ---------------------------------------------------------------------------


def _load_preset_raw(subject_id: str) -> dict[str, Any]:
    path = PRESETS_DIR / f"{subject_id}.json"
    if not path.is_file():
        raise SubjectNotFoundError(subject_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to parse subject pack %s", path)
        raise SubjectNotFoundError(subject_id) from None
    if not isinstance(raw, dict) or not raw.get("id"):
        raise SubjectNotFoundError(subject_id)
    return raw


def _preset_ids() -> set[str]:
    if not PRESETS_DIR.is_dir():
        return set()
    return {p.name[:-5] for p in PRESETS_DIR.glob("*.json") if p.suffix == ".json"}


def _json_subject_ids(editable_root: Path) -> set[str]:
    """Union of editable copies and built-in presets (fallback catalog)."""
    ids = set(_preset_ids())
    if editable_root.is_dir():
        ids.update(p.name[:-5] for p in editable_root.glob("*.json") if p.suffix == ".json")
    return ids


def _load_json_raw(editable_root: Path, subject_id: str) -> dict[str, Any]:
    """Editable copy wins; built-in preset is the fallback."""
    editable = editable_root / f"{subject_id}.json"
    if editable.is_file():
        try:
            raw = json.loads(editable.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("id"):
                return raw
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to parse editable subject pack %s", editable)
    return _load_preset_raw(subject_id)


def _parse_question(kp_id: str, row: dict[str, Any], index: int) -> SubjectQuestion:
    qid = str(row.get("id") or f"{kp_id}-q{index + 1}")
    return SubjectQuestion(
        id=qid,
        kp_id=kp_id,
        question=str(row.get("question") or ""),
        q_type=str(row.get("q_type") or "choice"),
        options=[str(o) for o in (row.get("options") or [])],
        answer=str(row.get("answer") or ""),
        explanation=str(row.get("explanation") or ""),
        difficulty=str(row.get("difficulty") or "medium"),
        created_by=str(row.get("created_by") or "system"),
        created_at=float(row.get("created_at") or time.time()),
        updated_at=float(row.get("updated_at") or time.time()),
    )


def _parse_kp(module_id: str, row: dict[str, Any], index: int) -> SubjectKnowledgePoint:
    kp_id = str(row.get("id") or "")
    questions = [_parse_question(kp_id, q, qi) for qi, q in enumerate(row.get("questions") or [])]
    return SubjectKnowledgePoint(
        id=kp_id,
        module_id=module_id,
        name=str(row.get("name") or ""),
        kp_type=str(row.get("kp_type") or "procedure"),
        order_no=int(row.get("order_no") or index + 1),
        openmaic_stage_id=str(row.get("openmaic_stage_id") or ""),
        openmaic_url=str(row.get("openmaic_url") or ""),
        questions=questions,
        created_at=float(row.get("created_at") or time.time()),
        updated_at=float(row.get("updated_at") or time.time()),
    )


def _parse_module(subject_id: str, row: dict[str, Any], index: int) -> SubjectModule:
    module_id = str(row.get("id") or "")
    kps = [_parse_kp(module_id, kp, ki) for ki, kp in enumerate(row.get("knowledge_points") or [])]
    return SubjectModule(
        id=module_id,
        subject_id=subject_id,
        name=str(row.get("name") or ""),
        order_no=int(row.get("order_no") or index + 1),
        pass_threshold=float(row.get("pass_threshold") or 0.7),
        knowledge_points=kps,
        created_at=float(row.get("created_at") or time.time()),
        updated_at=float(row.get("updated_at") or time.time()),
    )


def parse_subject(raw: dict[str, Any]) -> Subject:
    subject_id = str(raw.get("id") or "")
    modules = [_parse_module(subject_id, m, mi) for mi, m in enumerate(raw.get("modules") or [])]
    return Subject(
        id=subject_id,
        name=str(raw.get("name") or subject_id),
        stage=str(raw.get("stage") or ""),
        grade=str(raw.get("grade") or ""),
        textbook=str(raw.get("textbook") or ""),
        status=str(raw.get("status") or "active"),
        modules=modules,
        created_at=float(raw.get("created_at") or time.time()),
        updated_at=float(raw.get("updated_at") or time.time()),
    )


class SubjectPackService:
    """Read/write access to the global subject-pack catalog.

    Writes always go to the authoritative backend (MySQL when available,
    otherwise the editable JSON copy under the runtime data root).  Reads come
    from the same backend; when MySQL is configured it is auto-seeded from the
    built-in presets on first access.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._editable_root = root or (get_runtime_data_root() / "subject_pack")
        self._editable_root.mkdir(parents=True, exist_ok=True)
        self._mysql_store: Any | None = None
        self._mysql_ready: bool | None = None

    # -- backend selection --------------------------------------------------

    def _use_mysql(self) -> Any | None:
        """Return the MySQL store when it is reachable, else ``None``.

        Reachability is probed once per process: a successful connection makes
        ``self._mysql_store`` sticky.  A failed probe falls back to JSON for
        the rest of the process (no per-request connect storms).
        """
        if self._mysql_ready is not None:
            return self._mysql_store

        try:
            from deeptutor.services.session.mysql_store import _mysql_settings
            from deeptutor.services.subject_pack.mysql_store import SubjectMySQLStore

            if not _mysql_settings().get("host"):
                raise ConnectionError("no MySQL host configured")
            store = SubjectMySQLStore()
            if not store._ping():
                raise ConnectionError("MySQL unreachable")
            store.ensure_schema()
            self._seed_mysql_if_empty(store)
            self._mysql_store = store
            self._mysql_ready = True
            logger.info("Subject packs backed by MySQL (dt_subject* tables).")
        except Exception:
            logger.info("Subject packs backed by presets JSON (no reachable MySQL).")
            self._mysql_store = None
            self._mysql_ready = False
        return self._mysql_store

    def _seed_mysql_if_empty(self, store: Any) -> None:
        """Populate dt_subject from presets when no subject rows exist yet."""
        try:
            if store.list_catalog():
                return
        except Exception:
            logger.exception("Failed to list subjects while deciding MySQL seed.")
            return
        for subject_id in sorted(_preset_ids()):
            try:
                subject = parse_subject(_load_preset_raw(subject_id))
            except SubjectNotFoundError:
                continue
            try:
                store.save_subject(subject)
                logger.info("Seeded subject pack %s into dt_subject.", subject_id)
            except Exception:
                logger.exception("Failed to seed subject %s into MySQL.", subject_id)

    # -- queries ------------------------------------------------------------

    def list_catalog(self) -> list[dict[str, Any]]:
        store = self._use_mysql()
        if store is not None:
            try:
                return store.list_catalog()
            except Exception:
                logger.exception("MySQL subject catalog read failed; falling back to presets.")
        rows: list[dict[str, Any]] = []
        for subject_id in sorted(_json_subject_ids(self._editable_root)):
            try:
                subject = self.get_subject(subject_id)
            except SubjectNotFoundError:
                continue
            rows.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "stage": subject.stage,
                    "grade": subject.grade,
                    "textbook": subject.textbook,
                    "status": subject.status,
                    "module_count": len(subject.modules),
                    "kp_count": sum(len(m.knowledge_points) for m in subject.modules),
                }
            )
        return rows

    def list_subjects(self) -> list[Subject]:
        """Full tree of every seeded subject (used rarely; prefer catalog)."""
        return [
            self.get_subject(subject_id)
            for subject_id in sorted(_json_subject_ids(self._editable_root))
        ]

    def get_subject(self, subject_id: str, *, include_modules: bool = True) -> Subject:
        store = self._use_mysql()
        if store is not None:
            try:
                return store.get_subject(subject_id, include_modules=include_modules)
            except KeyError:
                raise SubjectNotFoundError(subject_id) from None
            except Exception:
                logger.exception("MySQL subject read failed for %s; falling back.", subject_id)
        return parse_subject(_load_json_raw(self._editable_root, subject_id))

    # -- write --------------------------------------------------------------

    def save_subject(self, subject: Subject) -> Subject:
        """Persist a whole subject tree to the authoritative backend.

        Returns the stored subject (re-read for consistent timestamps).
        """
        store = self._use_mysql()
        if store is not None:
            store.save_subject(subject)
            return self.get_subject(subject.id)
        # No MySQL: keep an editable JSON copy under the runtime data root.
        payload = subject.to_dict()
        payload["updated_at"] = time.time()
        atomic_write_json(self._editable_root / f"{subject.id}.json", payload)
        return subject

    def seed_from_data(self, data: dict[str, Any], subject_id: str | None = None) -> Subject:
        """Persist a subject pack from raw JSON (OpenMAIC pipeline / admin)."""
        sid = subject_id or str(data.get("id") or "").strip()
        if not sid:
            raise ValueError("Subject id is required.")
        payload = dict(data)
        payload["id"] = sid
        subject = parse_subject(payload)
        return self.save_subject(subject)


class _SubjectPackServiceSingleton:
    _instance: SubjectPackService | None = None


def get_subject_service() -> SubjectPackService:
    if _SubjectPackServiceSingleton._instance is None:
        _SubjectPackServiceSingleton._instance = SubjectPackService()
    return _SubjectPackServiceSingleton._instance


__all__ = [
    "PRESETS_DIR",
    "SubjectNotFoundError",
    "SubjectPackService",
    "get_subject_service",
]
