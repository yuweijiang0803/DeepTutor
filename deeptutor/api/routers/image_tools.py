"""Stateless image-processing endpoints (auth-gated).

``POST /api/v1/image/scan-enhance`` — the crop modal's "scan effect": send
the full page photo, get back a deskewed + denoised + binarized page ready
for printing.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.services.scan_enhance import ScanEnhanceOptions, enhance_scan

router = APIRouter()


class ScanEnhanceRequest(BaseModel):
    image_data_url: str
    deskew: bool = True
    denoise: bool = True
    cleanup: bool = True
    block_size: int = Field(default=31, ge=3, le=101)
    c: float = Field(default=15.0, ge=0.0, le=50.0)


class ScanEnhanceResponse(BaseModel):
    image_data_url: str


@router.post("/scan-enhance", response_model=ScanEnhanceResponse)
def scan_enhance(payload: ScanEnhanceRequest) -> dict[str, str]:
    """Deskew + denoise + adaptive-binarize a page image. Sync (threadpool)."""
    try:
        out = enhance_scan(
            payload.image_data_url,
            ScanEnhanceOptions(
                deskew=payload.deskew,
                denoise=payload.denoise,
                cleanup=payload.cleanup,
                block_size=payload.block_size,
                c=payload.c,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Scan enhance failed: {exc}")
    return {"image_data_url": out}
