"""OpenMAIC discovery proxy — surface published AI courses inside DeepTutor.

OpenMAIC runs its own public "discover" feed of published, non-deleted
courses (`GET /api/discover`, share-link model, no login).  DeepTutor proxies
that feed so learners can browse OpenMAIC courses from DeepTutor; cards open
the OpenMAIC classroom page (`/classroom/<id>`) directly in a new tab.
Lessons generated inside DeepTutor (course detail / chat) are still embedded
through the watch player — matching the agreed split: OpenMAIC produces
content, DeepTutor fronts it.

Base URL resolution mirrors ``deeptutor/tools/generate_explanation.py``:
``OPENMAIC_BASE_URL`` wins, otherwise the production domain.
"""

from __future__ import annotations

import logging
import os

import aiohttp
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

OPENMAIC_BASE_URL = os.environ.get(
    "OPENMAIC_BASE_URL", "https://learn.hourofai.cn"
).rstrip("/")

router = APIRouter()


@router.get("/discover")
async def discover_courses() -> dict[str, object]:
    """Published OpenMAIC courses, mapped to playable lesson URLs.

    The raw OpenMAIC payload is passed through unchanged (id / name /
    description / updatedAt / publishedAt / cover), plus a ``lesson_url`` each
    card can open: the OpenMAIC classroom page for that course. Classroom
    reads are public by id (share-link model) — no login required.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OPENMAIC_BASE_URL}/api/discover",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"OpenMAIC discover failed (HTTP {resp.status}).",
                    )
                payload = await resp.json()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenMAIC discover request failed: %s", exc)
        raise HTTPException(status_code=502, detail="OpenMAIC 课件服务不可达。") from exc

    courses = payload.get("courses", []) if isinstance(payload, dict) else []
    if not isinstance(courses, list):
        courses = []
    normalized = []
    for raw in courses:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        course_id = str(raw["id"])
        normalized.append(
            {
                **raw,
                "id": course_id,
                # OpenMAIC 的公开课页面 — DeepTutor 卡片新标签页直达的目标。
                "lesson_url": f"{OPENMAIC_BASE_URL}/classroom/{course_id}",
            }
        )
    return {"base_url": OPENMAIC_BASE_URL, "courses": normalized}
