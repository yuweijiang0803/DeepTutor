"""Question Review capability — mistake-book organising driven by the chat loop.

Same shape as ``mastery_path``: the capability only marks the turn as review
mode, then runs the standard agentic chat pipeline. The loop capability mounts
the ``question_bank`` tool unconditionally while the mode is active (even for a
learner whose bank is still empty — the first job is often to create a
category) and injects the organising playbook.

Playbook axioms (enforced in ``prompts/{lang}/system.md``, not in code):
- **never claim a write the tools did not confirm** — the exact failure mode a
  bare chat conversation produces ("I filed it") when the model narrates a
  completion instead of calling the tool;
- **never add entries to the bank on the model's own initiative** — ``add`` is
  only used when the learner explicitly asks to enter new mistakes.
"""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


class QuestionReviewCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="question_review",
        description=(
            "Review and organise the learner's question bank: file wrong "
            "answers into categories, create new ones, and add new mistakes "
            "when asked."
        ),
        stages=["responding"],
        tools_used=["question_bank", "rag", "ask_user"],
        cli_aliases=["review", "questions"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.metadata["question_review_mode"] = True
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)


__all__ = ["QuestionReviewCapability"]
