"""Generate an AI explanation course via OpenMAIC, playable back in DeepTutor.

The agent calls this tool when the learner needs a short structured
explanation (a few narrated pages) that plain text cannot carry well.
OpenMAIC runs its multi-agent course pipeline and returns a classroom;
DeepTutor points the learner at the watch player (iframe) for it.

OpenMAIC base URL resolution mirrors ``deeptutor/api/routers/openmaic.py``:
``OPENMAIC_BASE_URL`` wins, otherwise the production domain. Local dev can
point it at ``http://localhost:3000``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

OPENMAIC_BASE_URL = os.environ.get(
    "OPENMAIC_BASE_URL", "https://learn.hourofai.cn"
).rstrip("/")
POLL_INTERVAL_S = 5
TIMEOUT_S = 1200  # OpenMAIC 生成一课约 10-12 分钟，放宽到 20 分钟


@dataclass(frozen=True)
class GenerateOutcome:
    ok: bool
    message: str
    watch_url: str = ""
    classroom_id: str = ""
    scene_count: int = 0


async def run_generate_explanation(topic: str, extra_context: str = "") -> GenerateOutcome:
    """Ask OpenMAIC to generate a short explanation course on ``topic``.

    Returns a watch URL (``<base>/watch/<classroomId>``) the DeepTutor
    frontend can open in the embedded player.
    """
    import aiohttp

    requirement = topic.strip()
    if not requirement:
        return GenerateOutcome(ok=False, message="需要提供要讲解的知识点。")
    if extra_context:
        requirement = f"{requirement}\n\n学习上下文：{extra_context}"
    requirement += "\n\n要求：生成一个简短的讲解（1-3 页），第一页讲清概念，后续可举例或小测。"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENMAIC_BASE_URL}/api/generate-classroom",
                # enableTTS=True：生成时用 OpenMAIC 配置的 TTS（豆包）预合成讲解音频，
                # 课堂播放时直接播文件（音质好）；代价是生成更慢。
                json={"requirement": requirement, "enableTTS": True},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status not in (200, 202):
                    return GenerateOutcome(
                        ok=False, message=f"OpenMAIC 生成请求失败（HTTP {resp.status}）。"
                    )
                data = await resp.json()
            job_id = data.get("jobId")
            if not job_id:
                return GenerateOutcome(ok=False, message="OpenMAIC 未返回 jobId。")
            poll_path = data.get("pollUrl") or f"/api/generate-classroom/{job_id}"
            if not poll_path.startswith("/"):
                poll_path = "/" + poll_path

            elapsed = 0
            while elapsed < TIMEOUT_S:
                await asyncio.sleep(POLL_INTERVAL_S)
                elapsed += POLL_INTERVAL_S
                async with session.get(
                    f"{OPENMAIC_BASE_URL}{poll_path}",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        continue
                    state = await resp.json()
                if state.get("done"):
                    result = state.get("result") or {}
                    classroom_id = result.get("id")
                    scene_count = int(result.get("scenesCount") or 0)
                    if not classroom_id:
                        return GenerateOutcome(ok=False, message="生成完成但缺少 classroomId。")
                    # /watch/<id> 是 OpenMAIC 专为 DeepTutor 嵌入做的讲解播放页：
                    # 干净无导航、翻页时 postMessage 当前场景上下文（供学生提问注入）。
                    watch_url = f"{OPENMAIC_BASE_URL}/watch/{classroom_id}"
                    logger.info(
                        "generate_explanation ok: classroom_id=%s scenes=%s url=%s",
                        classroom_id,
                        scene_count,
                        watch_url,
                    )
                    return GenerateOutcome(
                        ok=True,
                        message=f"讲解已生成（{scene_count} 页），可以播放了。",
                        watch_url=watch_url,
                        classroom_id=classroom_id,
                        scene_count=scene_count,
                    )
                if state.get("status") == "failed":
                    return GenerateOutcome(ok=False, message="OpenMAIC 生成失败，请重试。")
            return GenerateOutcome(ok=False, message="OpenMAIC 生成超时，请稍后重试。")
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_explanation failed: %s", exc)
        return GenerateOutcome(ok=False, message=f"生成讲解出错：{exc}")


__all__ = ["GenerateOutcome", "run_generate_explanation"]
