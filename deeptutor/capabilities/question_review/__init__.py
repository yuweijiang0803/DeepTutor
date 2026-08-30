"""Question Review loop capability."""

# Only the loop capability is re-exported here. ``capability.py`` imports the
# chat pipeline, so the capability registry loads it by class path later —
# importing it here would create a circular import through agentic_pipeline.
from deeptutor.capabilities.question_review.loop import QuestionReviewLoopCapability

__all__ = ["QuestionReviewLoopCapability"]
