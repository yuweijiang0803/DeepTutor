"""错题页提取工具：整页照片 → 逐题识别 + 裁剪小图。

学生拍一张练习册页面，LLM 调用本工具：

1. 视觉模型分析整页，识别每道题（题号 / 区域 bbox / 判错 / 题目文本 / 是否有图）
2. 按 bbox 裁剪每道题的小图（水平自适应扩展到内容边界，垂直保持 LLM 框，
   避免把邻题卷进来），转成 base64 data URL
3. 返回结构化结果（metadata.page_questions），前端渲染成"题目卡片"供用户
   勾选确认后逐题入库
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from io import BytesIO
from typing import Any

import httpx

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

_PAGE_ANALYSIS_PROMPT = """分析这张练习册页面。识别页面中每一道题，只输出 JSON（不要任何多余文字）：

{"questions":[{"number":1,"bbox":[x,y,w,h],"is_wrong":true,"text":"题目标题或简述","has_figure":true,"question_type":"计算"}]}

规则：
- bbox 是归一化坐标 [0,1]，相对整张图片，格式 [x, y, width, height]
- 最重要：bbox 必须【完整包含该题的所有内容】，包括题目文字、手写答案、订正、
  批改痕迹、配套图形。宁可框大一些，也绝不能切掉任何内容。
- is_wrong：根据页面上批改标记（红叉/对勾/订正笔迹）判断这题是否做错；不确定填 false
- text：题目简短描述（开头几个字即可）
- has_figure：题目是否带图（如几何图形）
- question_type：题目类型，如 计算/应用题/几何/填空/选择/判断 等"""


def _active_llm_config() -> dict[str, str]:
    """Read the deployment's active LLM (vision-capable) model config."""
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog = get_model_catalog_service().load()
    llm = (catalog or {}).get("services", {}).get("llm", {}) or {}
    profiles = llm.get("profiles", []) or []
    profile = next(
        (p for p in profiles if p.get("id") == llm.get("active_profile_id")), None
    )
    if profile is None:
        profile = profiles[0] if profiles else {}
    model = next(
        (m for m in (profile.get("models") or []) if m.get("id") == llm.get("active_model_id")),
        None,
    ) or ((profile.get("models") or [{}])[0])
    return {
        "model": model.get("model") or model.get("name") or "",
        "api_key": profile.get("api_key") or "",
        "base_url": (profile.get("base_url") or "").rstrip("/"),
    }


async def analyze_page(image_data_url: str) -> list[dict[str, Any]]:
    """Vision LLM analyzes a full page photo into a question list (with bbox)."""
    cfg = _active_llm_config()
    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PAGE_ANALYSIS_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    url = f"{cfg['base_url']}/chat/completions"

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text.strip())
    questions = data.get("questions", []) or []
    for q in questions:
        q.setdefault("number", 0)
        q.setdefault("is_wrong", False)
        q.setdefault("text", "")
        q.setdefault("has_figure", False)
        q.setdefault("question_type", "")
    return questions


def _crop_question_to_data_url(
    image_data_url: str, bbox: list[float], padding_ratio: float = 0.03
) -> str:
    """Crop one question region (horizontal adaptive + vertical fixed) to a data URL."""
    from PIL import Image

    # Decode source image
    raw = base64.b64decode(image_data_url.split(",", 1)[-1])
    img = Image.open(BytesIO(raw)).convert("RGB")
    W, H = img.size
    try:
        import numpy as np

        arr = np.asarray(img.convert("L"))
        ink = arr < 180
    except ImportError:
        ink = None

    x, y, w, h = [float(v) for v in bbox]
    x0, y0 = int(x * W), int(y * H)
    x1, y1 = int((x + w) * W), int((y + h) * H)

    # Horizontal: extend to the content boundary within this question's band.
    if ink is not None:
        while x0 > 0 and ink[y0:y1, x0 - 1].any():
            x0 -= 1
        while x1 < W and ink[y0:y1, x1].any():
            x1 += 1

    # Vertical: keep the LLM box, only add a small pad (avoid dragging in the
    # neighbouring question).
    pad = int(padding_ratio * H)
    y0 = max(0, y0 - pad)
    y1 = min(H, y1 + pad)
    # Safety padding around the final box.
    pad_x = int(0.01 * W)
    x0 = max(0, x0 - pad_x)
    x1 = min(W, x1 + pad_x)

    crop = img.crop((x0, y0, x1, y1))
    buf = BytesIO()
    crop.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


class ExtractPageQuestionsTool(BaseTool):
    """Analyze a practice-page photo, split it into per-question crops."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="extract_page_questions",
            description=(
                "Analyze a photographed practice-exercise page, detect every "
                "question, and produce a per-question cropped image plus "
                "correctness judgment. Requires an attached image. Use when the "
                "user wants to collect wrong questions from a photo of a whole "
                "page. The result renders as a card for the user to confirm "
                "which are wrong before they are saved."
            ),
            parameters=[
                ToolParameter(
                    name="question",
                    type="string",
                    description="What the user wants (e.g. 收集这页的错题).",
                    required=False,
                ),
                ToolParameter(
                    name="image_base64",
                    type="string",
                    description=(
                        "Base64-encoded image (data URI or raw). Injected from "
                        "attachments when called via function-calling."
                    ),
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        image_base64 = kwargs.get("image_base64", "")
        if not image_base64:
            return ToolResult(
                content="No image provided. This tool requires an attached page photo.",
                success=False,
            )
        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"

        try:
            questions = await analyze_page(image_base64)
        except Exception as exc:
            return ToolResult(
                content=f"页面分析失败: {type(exc).__name__}: {exc}",
                success=False,
            )

        for q in questions:
            try:
                q["image_data_url"] = _crop_question_to_data_url(image_base64, q["bbox"])
            except Exception:
                q["image_data_url"] = ""

        wrong = sum(1 for q in questions if q.get("is_wrong"))
        return ToolResult(
            content=(
                f"识别到 {len(questions)} 道题，其中 {wrong} 道判定为错题。"
                "请把题目卡片展示给用户确认后保存。"
            ),
            metadata={"page_questions": questions},
        )


__all__ = ["ExtractPageQuestionsTool"]
