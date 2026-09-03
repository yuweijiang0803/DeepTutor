"""Subject-pack domain models.

A subject pack is the global, textbook-aligned content tree that the sync
learning loop (and later mastery paths) reference by stable semantic ids:

    Subject (dt_subject) → Module / chapter (dt_subject_module) → KnowledgePoint
    (dt_subject_kp) → Question (dt_subject_question)

Content is pre-set and shared across learners (no ``user_id``).  Each
knowledge point may reference an OpenMAIC-generated course stage that explains
it — the stage body lives in OpenMAIC's store, DeepTutor only keeps the id/url.

The semantic id scheme doubles as the ``LearningModule.id`` / ``KnowledgePoint.id``
used by the mastery engine, so a seeded tree maps onto mastery with zero
translation, e.g. ``math-rjb-7a-u1-k2``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

KnowledgePointType = Literal["memory", "procedure", "concept", "design"]
QuestionType = Literal["choice", "fill_in_blank", "written"]
Difficulty = Literal["easy", "medium", "hard"]


@dataclass(slots=True)
class SubjectQuestion:
    id: str
    kp_id: str
    question: str
    q_type: QuestionType = "choice"
    options: list[str] = field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    difficulty: Difficulty = "medium"
    created_by: str = "system"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SubjectKnowledgePoint:
    id: str
    module_id: str
    name: str
    kp_type: KnowledgePointType = "procedure"
    order_no: int = 0
    # OpenMAIC 课件引用（本体在 OpenMAIC 侧，这里只存引用，可为空）
    openmaic_stage_id: str = ""
    openmaic_url: str = ""
    questions: list[SubjectQuestion] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SubjectModule:
    id: str
    subject_id: str
    name: str
    order_no: int = 0
    pass_threshold: float = 0.7
    knowledge_points: list[SubjectKnowledgePoint] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Subject:
    id: str
    name: str
    stage: str = ""  # junior / senior / primary …
    grade: str = ""  # 七年级上册
    textbook: str = ""  # 人教版
    status: str = "active"
    modules: list[SubjectModule] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> float:
    return time.time()


__all__ = [
    "Subject",
    "SubjectModule",
    "SubjectKnowledgePoint",
    "SubjectQuestion",
    "KnowledgePointType",
    "QuestionType",
    "Difficulty",
    "_now",
]
