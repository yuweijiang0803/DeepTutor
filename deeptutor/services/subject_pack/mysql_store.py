"""MySQL-backed subject-pack store.

Persists the global ``dt_subject*`` tables.  Mirrors the synchronous pymysql
style of :mod:`deeptutor.learning.mysql_storage` and reuses the shared MySQL
connection settings — the store connects whenever a host is configured and the
database answers, independent of the session ``storage_mode()`` switch, because
subject packs are global content rather than per-user session state.

Concurrency model: subject packs are pre-set content that changes rarely (an
admin re-import replaces a whole tree).  Each save rewrites one subject's rows
inside a transaction — no per-node diffing, no revision CAS needed.
"""

from __future__ import annotations

import json
import time
from typing import Any

from deeptutor.services.subject_pack.models import (
    Subject,
    SubjectKnowledgePoint,
    SubjectModule,
    SubjectQuestion,
)
from deeptutor.services.subject_pack.schema import SUBJECT_SCHEMA_SQL


def subject_mysql_conn():
    """Open a synchronous pymysql connection from the shared MySQL settings."""
    import pymysql

    from deeptutor.services.session.mysql_store import _mysql_settings

    cfg = _mysql_settings()
    if not cfg.get("host"):
        raise ConnectionError("No MySQL host configured (mysql.json / MYSQL_HOST).")
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


class SubjectMySQLStore:
    """Read/write access to the global subject-pack tables."""

    def __init__(self) -> None:
        self._schema_ready = False

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Create the dt_subject* tables idempotently on first use."""
        if self._schema_ready:
            return
        conn = subject_mysql_conn()
        try:
            with conn.cursor() as cur:
                for stmt in SUBJECT_SCHEMA_SQL.split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()
        self._schema_ready = True

    @staticmethod
    def _ping() -> bool:
        """True when the MySQL server is reachable with the configured creds."""
        try:
            conn = subject_mysql_conn()
        except Exception:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:
            return False
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Row parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _question_from_row(row: dict[str, Any]) -> SubjectQuestion:
        options = json.loads(row.get("options_json") or "[]") or []
        return SubjectQuestion(
            id=row["id"],
            kp_id=row["kp_id"],
            question=row["question"] or "",
            q_type=row["q_type"] or "choice",
            options=list(options) if isinstance(options, list) else [],
            answer=row["answer"] or "",
            explanation=row["explanation"] or "",
            difficulty=row["difficulty"] or "medium",
            created_by=row["created_by"] or "system",
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _kp_from_row(row: dict[str, Any]) -> SubjectKnowledgePoint:
        return SubjectKnowledgePoint(
            id=row["id"],
            module_id=row["module_id"],
            name=row["name"],
            kp_type=row["kp_type"] or "procedure",
            order_no=int(row["order_no"] or 0),
            openmaic_stage_id=row["openmaic_stage_id"] or "",
            openmaic_url=row["openmaic_url"] or "",
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _module_from_row(row: dict[str, Any]) -> SubjectModule:
        return SubjectModule(
            id=row["id"],
            subject_id=row["subject_id"],
            name=row["name"],
            order_no=int(row["order_no"] or 0),
            pass_threshold=float(row["pass_threshold"] or 0.7),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_catalog(self) -> list[dict[str, Any]]:
        """Subject metadata plus module/kp counts (row-count subqueries)."""
        conn = subject_mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.name, s.stage, s.grade, s.textbook, s.status,
                           (SELECT COUNT(*) FROM dt_subject_module m
                             WHERE m.subject_id = s.id) AS module_count,
                           (SELECT COUNT(*) FROM dt_subject_kp k
                             JOIN dt_subject_module m ON k.module_id = m.id
                            WHERE m.subject_id = s.id) AS kp_count
                      FROM dt_subject s
                     ORDER BY s.grade, s.id
                    """
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "stage": r["stage"],
                "grade": r["grade"],
                "textbook": r["textbook"],
                "status": r["status"],
                "module_count": int(r["module_count"] or 0),
                "kp_count": int(r["kp_count"] or 0),
            }
            for r in rows
        ]

    def get_subject(self, subject_id: str, *, include_modules: bool = True) -> Subject:
        conn = subject_mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dt_subject WHERE id=%s", (subject_id,)
                )
                srow = cur.fetchone()
                if srow is None:
                    raise KeyError(subject_id)

                subject = Subject(
                    id=srow["id"],
                    name=srow["name"],
                    stage=srow["stage"],
                    grade=srow["grade"],
                    textbook=srow["textbook"],
                    status=srow["status"],
                    created_at=float(srow["created_at"]),
                    updated_at=float(srow["updated_at"]),
                )
                if not include_modules:
                    return subject

                cur.execute(
                    "SELECT * FROM dt_subject_module WHERE subject_id=%s ORDER BY order_no, id",
                    (subject_id,),
                )
                module_rows = cur.fetchall()
                for mrow in module_rows:
                    module = self._module_from_row(mrow)
                    cur.execute(
                        "SELECT * FROM dt_subject_kp WHERE module_id=%s ORDER BY order_no, id",
                        (module.id,),
                    )
                    for krow in cur.fetchall():
                        kp = self._kp_from_row(krow)
                        cur.execute(
                            "SELECT * FROM dt_subject_question WHERE kp_id=%s ORDER BY id",
                            (kp.id,),
                        )
                        kp.questions = [self._question_from_row(q) for q in cur.fetchall()]
                        module.knowledge_points.append(kp)
                    subject.modules.append(module)
        finally:
            conn.close()
        return subject

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_subject(self, subject: Subject) -> None:
        """Rewrite one subject's whole tree in a transaction (idempotent)."""
        now = time.time()
        conn = subject_mysql_conn()
        try:
            with conn.cursor() as cur:
                # Delete existing tree bottom-up (no FK cascade configured).
                module_ids = [m.id for m in subject.modules]
                for module_id in module_ids:
                    cur.execute("DELETE FROM dt_subject_question WHERE kp_id IN "
                                "(SELECT id FROM dt_subject_kp WHERE module_id=%s)", (module_id,))
                    cur.execute("DELETE FROM dt_subject_kp WHERE module_id=%s", (module_id,))
                cur.execute("DELETE FROM dt_subject_module WHERE subject_id=%s", (subject.id,))
                cur.execute("DELETE FROM dt_subject WHERE id=%s", (subject.id,))

                cur.execute(
                    """INSERT INTO dt_subject
                       (id, name, stage, grade, textbook, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        subject.id,
                        subject.name,
                        subject.stage,
                        subject.grade,
                        subject.textbook,
                        subject.status,
                        subject.created_at or now,
                        now,
                    ),
                )
                for module in subject.modules:
                    cur.execute(
                        """INSERT INTO dt_subject_module
                           (id, subject_id, name, order_no, pass_threshold, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            module.id,
                            subject.id,
                            module.name,
                            module.order_no,
                            module.pass_threshold,
                            module.created_at or now,
                            now,
                        ),
                    )
                    for kp in module.knowledge_points:
                        cur.execute(
                            """INSERT INTO dt_subject_kp
                               (id, module_id, name, kp_type, order_no,
                                openmaic_stage_id, openmaic_url, created_at, updated_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                kp.id,
                                module.id,
                                kp.name,
                                kp.kp_type,
                                kp.order_no,
                                kp.openmaic_stage_id or "",
                                kp.openmaic_url or "",
                                kp.created_at or now,
                                now,
                            ),
                        )
                        for question in kp.questions:
                            cur.execute(
                                """INSERT INTO dt_subject_question
                                   (id, kp_id, question, q_type, options_json, answer,
                                    explanation, difficulty, created_by, created_at, updated_at)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    question.id,
                                    kp.id,
                                    question.question,
                                    question.q_type,
                                    json.dumps(question.options, ensure_ascii=False),
                                    question.answer,
                                    question.explanation,
                                    question.difficulty,
                                    question.created_by,
                                    question.created_at or now,
                                    now,
                                ),
                            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def has_subject(self, subject_id: str) -> bool:
        conn = subject_mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dt_subject WHERE id=%s", (subject_id,))
                return cur.fetchone() is not None
        finally:
            conn.close()


__all__ = ["SubjectMySQLStore", "subject_mysql_conn"]
