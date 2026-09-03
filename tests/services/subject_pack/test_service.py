"""Subject-pack service tests — JSON presets fallback path (no MySQL)."""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subject_pack import (
    PRESETS_DIR,
    SubjectNotFoundError,
    SubjectPackService,
)
from deeptutor.services.subject_pack.models import (
    Subject,
    SubjectKnowledgePoint,
    SubjectModule,
    SubjectQuestion,
)
from deeptutor.services.subject_pack.service import (
    _load_preset_raw,
    parse_subject,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    # Force the JSON fallback: make the MySQL probe fail fast.
    monkeypatch.setattr(
        "deeptutor.services.subject_pack.service.SubjectPackService._use_mysql",
        lambda self: None,
    )
    return SubjectPackService(root=tmp_path / "subject_pack")


def _seed_payload() -> dict:
    return {
        "id": "math-rjb-7a",
        "name": "初中数学",
        "stage": "junior",
        "grade": "七年级上册",
        "textbook": "人教版",
        "modules": [
            {
                "id": "math-rjb-7a-u1",
                "name": "第一章 有理数",
                "order_no": 1,
                "knowledge_points": [
                    {
                        "id": "math-rjb-7a-u1-k4",
                        "name": "绝对值",
                        "kp_type": "procedure",
                        "order_no": 4,
                        "questions": [
                            {
                                "id": "math-rjb-7a-u1-k4-q1",
                                "question": "|-3| 等于（ ）",
                                "q_type": "choice",
                                "options": ["3", "-3", "0", "±3"],
                                "answer": "A",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_preset_parses_full_tree():
    raw = _load_preset_raw("math-rjb-7a")
    subject = parse_subject(raw)
    assert subject.id == "math-rjb-7a"
    assert subject.grade == "七年级上册"
    assert len(subject.modules) == 4
    kp_count = sum(len(m.knowledge_points) for m in subject.modules)
    assert kp_count == 21


def test_parse_question_options_roundtrip():
    raw = _load_preset_raw("math-rjb-7a")
    subject = parse_subject(raw)
    abs_kp = None
    for module in subject.modules:
        for kp in module.knowledge_points:
            if kp.id == "math-rjb-7a-u1-k4":
                abs_kp = kp
    assert abs_kp is not None
    assert abs_kp.questions and abs_kp.questions[0].question.startswith("|-3|")
    assert abs_kp.questions[0].options == ["3", "-3", "0", "±3"]


def test_list_catalog(service):
    rows = service.list_catalog()
    assert rows, "presets must provide at least one subject"
    row = next(r for r in rows if r["id"] == "math-rjb-7a")
    assert row["module_count"] == 4
    assert row["kp_count"] == 21


def test_get_subject_missing_raises(service):
    with pytest.raises(SubjectNotFoundError):
        service.get_subject("no-such-subject")


def test_seed_from_data_writes_editable_copy(service):
    stored = service.seed_from_data(_seed_payload())
    assert isinstance(stored, Subject)
    assert stored.id == "math-rjb-7a"
    copy_file = service._editable_root / "math-rjb-7a.json"
    assert copy_file.is_file()
    reloaded = service.get_subject("math-rjb-7a")
    assert reloaded.name == "初中数学"


def test_editable_copy_wins_over_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.subject_pack.service.SubjectPackService._use_mysql",
        lambda self: None,
    )
    svc = SubjectPackService(root=tmp_path / "subject_pack")
    # Write an edited copy whose name differs from the preset.
    svc.seed_from_data(_seed_payload())
    (svc._editable_root / "math-rjb-7a.json").write_text(
        json.dumps(
            {
                "id": "math-rjb-7a",
                "name": "初中数学（改）",
                "grade": "七年级上册",
                "modules": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    subject = svc.get_subject("math-rjb-7a")
    assert subject.name == "初中数学（改）"
    assert subject.modules == []


def test_models_to_dict_shape():
    question = SubjectQuestion(
        id="q1", kp_id="k1", question="1+1=?", options=["2", "3"], answer="A"
    )
    kp = SubjectKnowledgePoint(id="k1", module_id="m1", name="加法", questions=[question])
    module = SubjectModule(id="m1", subject_id="s1", name="第一章", knowledge_points=[kp])
    subject = Subject(id="s1", name="学科", modules=[module])
    data = subject.to_dict()
    assert data["modules"][0]["knowledge_points"][0]["questions"][0]["answer"] == "A"
