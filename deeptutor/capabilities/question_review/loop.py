"""Question-review loop-capability hooks.

Reuses the full chat tool surface and unconditionally mounts the
``question_bank`` tool (which the base chat turn only auto-mounts when a bank
already has entries). The system block carries the organising playbook whose
hard rules close the "agent claimed it wrote but nothing changed" failure mode.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext


class QuestionReviewLoopCapability:
    """Turn-scoped integration for question-bank review/organising."""

    name = "question_review"
    owned_tools = ("question_bank",)

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("question_review_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("question_review", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("question_review", content)

    def finish_instruction(self, context: UnifiedContext, final_text: str) -> str | None:
        """No protocol guard needed — every write is tool-gated by design."""
        _ = (context, final_text)
        return None

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["QuestionReviewLoopCapability"]
