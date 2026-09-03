"""Subject-pack → mastery-path bridging tests (mapping is pure over models)."""

from __future__ import annotations

from deeptutor.api.routers.mastery_path import _learning_modules_from_subject
from deeptutor.services.subject_pack.models import (
    Subject,
    SubjectKnowledgePoint,
    SubjectModule,
)


def _sample_subject() -> Subject:
    kp1 = SubjectKnowledgePoint(
        id="math-rjb-7a-u1-k1",
        module_id="math-rjb-7a-u1",
        name="正数和负数",
        kp_type="concept",
        order_no=1,
    )
    kp2 = SubjectKnowledgePoint(
        id="math-rjb-7a-u1-k4",
        module_id="math-rjb-7a-u1",
        name="绝对值",
        kp_type="procedure",
        order_no=4,
    )
    module = SubjectModule(
        id="math-rjb-7a-u1",
        subject_id="math-rjb-7a",
        name="第一章 有理数",
        order_no=1,
        pass_threshold=0.8,
        knowledge_points=[kp1, kp2],
    )
    return Subject(
        id="math-rjb-7a",
        name="初中数学",
        stage="junior",
        grade="七年级上册",
        textbook="人教版",
        modules=[module],
    )


def test_maps_modules_and_preserves_ids():
    modules = _learning_modules_from_subject(_sample_subject())
    assert len(modules) == 1
    module = modules[0]
    assert module.id == "math-rjb-7a-u1"
    assert module.name == "第一章 有理数"
    assert module.order == 1
    assert module.pass_threshold == 0.8
    assert [kp.id for kp in module.knowledge_points] == [
        "math-rjb-7a-u1-k1",
        "math-rjb-7a-u1-k4",
    ]
    # 顺序与类型保持学科包定义。
    kp1, kp2 = module.knowledge_points
    assert kp1.type.value == "concept"
    assert kp2.type.value == "procedure"
    assert kp2.module_id == "math-rjb-7a-u1"


def test_unknown_kp_type_falls_back_to_concept():
    kp = SubjectKnowledgePoint(
        id="k-x",
        module_id="m-x",
        name="异常类型",
        kp_type="procedure",
        order_no=1,
    )
    # 直接改字段模拟脏数据（模型不做运行时校验）。
    kp.kp_type = "bogus"  # type: ignore[assignment]
    subject = _sample_subject()
    subject.modules[0].knowledge_points = [kp]
    modules = _learning_modules_from_subject(subject)
    assert modules[0].knowledge_points[0].type.value == "concept"
