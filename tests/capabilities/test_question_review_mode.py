"""The question_review mode: activation, playbook, and manifest."""

from __future__ import annotations

from deeptutor.capabilities.question_review import QuestionReviewLoopCapability
from deeptutor.capabilities.question_review.capability import QuestionReviewCapability
from deeptutor.core.context import UnifiedContext


def test_loop_activates_only_in_review_mode() -> None:
    loop = QuestionReviewLoopCapability()
    ctx = UnifiedContext(session_id="s", language="zh-CN", metadata={})
    assert loop.is_active(ctx) is False
    ctx.metadata["question_review_mode"] = True
    assert loop.is_active(ctx) is True
    assert loop.owned_tools == ("question_bank",)


def test_system_block_loads_zh_playbook() -> None:
    loop = QuestionReviewLoopCapability()
    ctx = UnifiedContext(
        session_id="s", language="zh-CN", metadata={"question_review_mode": True}
    )
    block = loop.system_block(ctx, language="zh-CN", prompts={})
    assert block is not None
    assert block.name == "question_review"
    # The hard rule that closes the "agent claimed it wrote" failure mode.
    assert "绝不擅自新增" in block.content
    assert "工具返回" in block.content


def test_system_block_inactive_returns_none() -> None:
    loop = QuestionReviewLoopCapability()
    ctx = UnifiedContext(session_id="s", language="zh-CN", metadata={})
    assert loop.system_block(ctx, language="zh-CN", prompts={}) is None


def test_capability_manifest() -> None:
    cap = QuestionReviewCapability()
    assert cap.manifest.name == "question_review"
    assert "question_bank" in cap.manifest.tools_used
    assert "review" in cap.manifest.cli_aliases
