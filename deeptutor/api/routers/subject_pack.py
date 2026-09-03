"""Subject-pack catalog + tree endpoints (global textbook-aligned content)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.services.subject_pack import (
    SubjectNotFoundError,
    get_subject_service,
)


class SubjectCreateRequest(BaseModel):
    """Upsert a whole subject pack (content produced elsewhere, e.g. OpenMAIC
    pipeline or an admin surface).  Replaces the editable copy for that id."""

    subject: dict[str, object] = Field(..., description="Full subject pack JSON.")
    subject_id: str = Field(default="", description="Optional override id.")


router = APIRouter()


@router.get("")
async def list_subjects() -> dict[str, object]:
    return {"subjects": get_subject_service().list_catalog()}


@router.get("/{subject_id}")
async def get_subject(subject_id: str) -> dict[str, object]:
    try:
        subject = get_subject_service().get_subject(subject_id)
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Subject not found") from exc
    return {"subject": subject.to_dict()}


@router.post("")
async def upsert_subject(payload: SubjectCreateRequest) -> dict[str, object]:
    try:
        subject = get_subject_service().seed_from_data(
            payload.subject, subject_id=payload.subject_id or None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"subject": subject.to_dict()}
