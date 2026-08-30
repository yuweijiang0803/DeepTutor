"use client";

import { useMemo, useRef, useState } from "react";
import { CheckCircle2, Crop, Loader2, Save, X } from "lucide-react";
import { upsertNotebookEntry } from "@/lib/notebook-api";

export interface PageQuestion {
  number: number;
  bbox: number[];
  is_wrong: boolean;
  text: string;
  has_figure?: boolean;
  question_type?: string;
  image_data_url?: string;
}

export function extractPageQuestions(
  events: Array<{ metadata?: unknown }> | undefined,
): PageQuestion[] | null {
  if (!events || events.length === 0) return null;
  for (const event of events) {
    const meta = event.metadata as
      | { tool_metadata?: { page_questions?: PageQuestion[] } }
      | undefined;
    if (meta?.tool_metadata?.page_questions?.length) {
      return meta.tool_metadata.page_questions;
    }
  }
  return null;
}

// ── 二次裁剪 ──────────────────────────────────────────────────────
// 在已裁剪的题目图上再调整裁剪范围。选择框用归一化坐标（相对图片显示
// 尺寸 0..1）存储，指针事件换算成归一化后写入 state，确认时按原图
// 分辨率画到 canvas 输出新的 data URL。

type CropSelection = { x: number; y: number; w: number; h: number };
type DragMode =
  | "draw"
  | "move"
  | "nw"
  | "n"
  | "ne"
  | "e"
  | "se"
  | "s"
  | "sw"
  | "w";

const HANDLE_CURSOR: Record<DragMode, string> = {
  draw: "crosshair",
  move: "move",
  nw: "nwse-resize",
  n: "ns-resize",
  ne: "nesw-resize",
  e: "ew-resize",
  se: "nwse-resize",
  s: "ns-resize",
  sw: "nesw-resize",
  w: "ew-resize",
};

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

function applyDrag(
  mode: DragMode,
  start: { x: number; y: number },
  init: CropSelection,
  cur: { x: number; y: number },
  minW: number,
  minH: number,
): CropSelection {
  switch (mode) {
    case "draw": {
      const x = clamp(Math.min(start.x, cur.x), 0, 1);
      const y = clamp(Math.min(start.y, cur.y), 0, 1);
      const w = clamp(Math.abs(cur.x - start.x), 0, 1 - x);
      const h = clamp(Math.abs(cur.y - start.y), 0, 1 - y);
      return { x, y, w, h };
    }
    case "move": {
      const dx = cur.x - start.x;
      const dy = cur.y - start.y;
      return {
        x: clamp(init.x + dx, 0, 1 - init.w),
        y: clamp(init.y + dy, 0, 1 - init.h),
        w: init.w,
        h: init.h,
      };
    }
    case "nw": {
      const x = clamp(cur.x, 0, init.x + init.w - minW);
      const y = clamp(cur.y, 0, init.y + init.h - minH);
      return { x, y, w: init.x + init.w - x, h: init.y + init.h - y };
    }
    case "n": {
      const y = clamp(cur.y, 0, init.y + init.h - minH);
      return { ...init, y, h: init.y + init.h - y };
    }
    case "ne": {
      const y = clamp(cur.y, 0, init.y + init.h - minH);
      return {
        x: init.x,
        y,
        w: clamp(cur.x - init.x, minW, 1 - init.x),
        h: init.y + init.h - y,
      };
    }
    case "e": {
      return { ...init, w: clamp(cur.x - init.x, minW, 1 - init.x) };
    }
    case "se": {
      return {
        x: init.x,
        y: init.y,
        w: clamp(cur.x - init.x, minW, 1 - init.x),
        h: clamp(cur.y - init.y, minH, 1 - init.y),
      };
    }
    case "s": {
      return { ...init, h: clamp(cur.y - init.y, minH, 1 - init.y) };
    }
    case "sw": {
      const x = clamp(cur.x, 0, init.x + init.w - minW);
      return { ...init, x, w: init.x + init.w - x };
    }
    case "w": {
      const x = clamp(cur.x, 0, init.x + init.w - minW);
      return { ...init, x, w: init.x + init.w - x };
    }
  }
}

/** 命中测试：返回拖拽模式。点中 8 个手柄 → 缩放；在框内 → 移动；否则新建选框。 */
function hitTest(
  x: number,
  y: number,
  sel: CropSelection | null,
  rect: { width: number; height: number },
): DragMode | null {
  if (!sel) return null;
  const px = x * rect.width;
  const py = y * rect.height;
  const sx = sel.x * rect.width;
  const sy = sel.y * rect.height;
  const sw = sel.w * rect.width;
  const sh = sel.h * rect.height;
  const h = 12; // 手柄命中半径（px）
  const near = (a: number, b: number) => Math.abs(a - b) <= h;
  if (near(px, sx) && near(py, sy)) return "nw";
  if (near(px, sx + sw) && near(py, sy)) return "ne";
  if (near(px, sx) && near(py, sy + sh)) return "sw";
  if (near(px, sx + sw) && near(py, sy + sh)) return "se";
  if (near(px, sx + sw / 2) && near(py, sy)) return "n";
  if (near(px, sx + sw / 2) && near(py, sy + sh)) return "s";
  if (near(px, sx) && near(py, sy + sh / 2)) return "w";
  if (near(px, sx + sw) && near(py, sy + sh / 2)) return "e";
  if (
    px >= sx &&
    px <= sx + sw &&
    py >= sy &&
    py <= sy + sh &&
    sw > h * 2 &&
    sh > h * 2
  ) {
    return "move";
  }
  return null;
}

const HANDLES: Array<{ mode: DragMode; left: string; top: string }> = [
  { mode: "nw", left: "0%", top: "0%" },
  { mode: "n", left: "50%", top: "0%" },
  { mode: "ne", left: "100%", top: "0%" },
  { mode: "e", left: "100%", top: "50%" },
  { mode: "se", left: "100%", top: "100%" },
  { mode: "s", left: "50%", top: "100%" },
  { mode: "sw", left: "0%", top: "100%" },
  { mode: "w", left: "0%", top: "50%" },
];

function CropImageModal({
  src,
  onCancel,
  onConfirm,
}: {
  src: string;
  onCancel: () => void;
  onConfirm: (dataUrl: string) => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [sel, setSel] = useState<CropSelection | null>(null);
  const [activeMode, setActiveMode] = useState<DragMode | null>(null);
  const dragRef = useRef<{
    mode: DragMode;
    start: { x: number; y: number };
    init: CropSelection;
  } | null>(null);

  const normPoint = (e: React.PointerEvent) => {
    const rect = imgRef.current!.getBoundingClientRect();
    return {
      x: clamp((e.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((e.clientY - rect.top) / rect.height, 0, 1),
      width: rect.width,
      height: rect.height,
    };
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!imgRef.current) return;
    const p = normPoint(e);
    e.currentTarget.setPointerCapture(e.pointerId);
    const mode = hitTest(p.x, p.y, sel, p);
    setActiveMode(mode ?? "draw");
    if (mode && mode !== "draw") {
      dragRef.current = { mode, start: { x: p.x, y: p.y }, init: sel! };
    } else {
      dragRef.current = { mode: "draw", start: { x: p.x, y: p.y }, init: { x: p.x, y: p.y, w: 0, h: 0 } };
      setSel({ x: p.x, y: p.y, w: 0, h: 0 });
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !imgRef.current) return;
    const p = normPoint(e);
    const minW = Math.min(8 / p.width, 0.1);
    const minH = Math.min(8 / p.height, 0.1);
    setSel(applyDrag(drag.mode, drag.start, drag.init, p, minW, minH));
  };

  const handlePointerUp = () => {
    dragRef.current = null;
    setActiveMode(null);
  };

  const handleConfirm = () => {
    const imgEl = imgRef.current;
    if (!imgEl || !sel) return;
    const nw = imgEl.naturalWidth;
    const nh = imgEl.naturalHeight;
    const x = Math.round(sel.x * nw);
    const y = Math.round(sel.y * nh);
    const w = Math.max(1, Math.round(sel.w * nw));
    const h = Math.max(1, Math.round(sel.h * nh));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(imgEl, x, y, w, h, 0, 0, w, h);
    onConfirm(canvas.toDataURL("image/png"));
  };

  const canConfirm = sel !== null && sel.w > 0.01 && sel.h > 0.01;
  const cursor = activeMode
    ? HANDLE_CURSOR[activeMode]
    : sel
      ? HANDLE_CURSOR["move"]
      : HANDLE_CURSOR["draw"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-fit max-w-[min(92vw,720px)] rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-[14px] font-semibold">调整裁剪范围</h4>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div
          className="relative inline-block select-none overflow-hidden rounded-md"
          style={{ touchAction: "none", cursor }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            ref={imgRef}
            src={src}
            alt="裁剪区域"
            draggable={false}
            className="block max-h-[55vh] max-w-[min(90vw,660px)] bg-white"
          />

          {sel && sel.w > 0.005 && sel.h > 0.005 ? (
            <div
              className="pointer-events-none absolute border-2 border-[var(--primary)]"
              style={{
                left: `${sel.x * 100}%`,
                top: `${sel.y * 100}%`,
                width: `${sel.w * 100}%`,
                height: `${sel.h * 100}%`,
              }}
            >
              {/* 选区外遮罩（box-shadow 向四周扩散，由父级 overflow-hidden 裁剪） */}
              <div
                className="absolute inset-0"
                style={{ boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)" }}
              />
              {HANDLES.map((hd) => (
                <div
                  key={hd.mode}
                  className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-[3px] border border-[var(--primary)] bg-white shadow"
                  style={{ left: hd.left, top: hd.top }}
                />
              ))}
            </div>
          ) : (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="rounded-md bg-black/55 px-2 py-1 text-[12px] text-white">
                在图片上拖动选择裁剪区域
              </span>
            </div>
          )}
        </div>

        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[13px] font-medium text-[var(--accent-foreground)] disabled:opacity-50"
          >
            确认裁剪
          </button>
        </div>
      </div>
    </div>
  );
}

interface PageQuestionsCardProps {
  questions: PageQuestion[];
  sessionId: string;
}

export function PageQuestionsCard({
  questions,
  sessionId,
}: PageQuestionsCardProps) {
  // Wrong by default from the LLM judgment; the learner can untick.
  const [wrongSet, setWrongSet] = useState<Set<number>>(
    () => new Set(questions.filter((q) => q.is_wrong).map((q) => q.number)),
  );
  // 二次裁剪后的图（按题目号覆盖原始 image_data_url）
  const [imageUrls, setImageUrls] = useState<Record<number, string>>({});
  const [cropNumber, setCropNumber] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [savedCount, setSavedCount] = useState(0);

  const wrongQuestions = useMemo(
    () => questions.filter((q) => wrongSet.has(q.number)),
    [questions, wrongSet],
  );

  const toggle = (number: number) => {
    setWrongSet((prev) => {
      const next = new Set(prev);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      return next;
    });
  };

  const imageSrcFor = (q: PageQuestion) =>
    imageUrls[q.number] ?? q.image_data_url;

  const croppedQuestion =
    cropNumber === null
      ? null
      : questions.find((q) => q.number === cropNumber) ?? null;

  const handleSave = async () => {
    setSaving(true);
    setError("");
    let count = 0;
    try {
      for (const q of wrongQuestions) {
        const imageSrc = imageSrcFor(q);
        const image = imageSrc
          ? [
              {
                base64: imageSrc.split(",")[1] ?? "",
                filename: `page_q${q.number}.png`,
                mime_type: "image/png",
              },
            ]
          : [];
        await upsertNotebookEntry({
          session_id: sessionId,
          question_id: `page_${Date.now()}_q${q.number}`,
          question: q.text || `第${q.number}题`,
          question_type: q.question_type || "",
          is_correct: false,
          user_answer_images: image,
        });
        count += 1;
      }
      setSavedCount(count);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="my-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-center gap-2">
        <h4 className="text-[14px] font-semibold">识别到 {questions.length} 道题</h4>
        <span className="text-[12px] text-[var(--muted-foreground)]">
          勾选的是错题，确认后存入错题本
        </span>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {questions.map((q) => {
          const wrong = wrongSet.has(q.number);
          const imageSrc = imageSrcFor(q);
          return (
            <div
              key={q.number}
              title={q.text}
              className={`rounded-lg border p-2 transition-colors ${
                wrong
                  ? "border-red-500/50 bg-red-500/5"
                  : "border-[var(--border)] bg-[var(--background)]/50"
              }`}
            >
              {imageSrc ? (
                <img
                  src={imageSrc}
                  alt={`第${q.number}题`}
                  className="max-h-40 w-full rounded-md border border-[var(--border)] object-contain bg-white"
                />
              ) : (
                <div className="flex h-24 items-center justify-center rounded-md border border-[var(--border)] text-[12px] text-[var(--muted-foreground)]">
                  {q.text || `第${q.number}题`}
                </div>
              )}

              <div className="mt-1.5 flex items-center justify-between gap-1 px-0.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] text-[var(--muted-foreground)]">
                    第{q.number}题
                  </span>
                  {imageSrc && (
                    <button
                      type="button"
                      onClick={() => setCropNumber(q.number)}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/50 hover:text-[var(--primary)]"
                    >
                      <Crop size={11} />
                      裁剪
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => toggle(q.number)}
                  className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] transition-colors ${
                    wrong
                      ? "text-red-500"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  }`}
                >
                  <CheckCircle2 size={13} />
                  {wrong ? "错题" : "不是错题"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving || done || wrongQuestions.length === 0}
          className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-[13px] font-medium text-[var(--accent-foreground)] disabled:opacity-50"
        >
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> 保存中…
            </>
          ) : done ? (
            <>
              <CheckCircle2 className="h-4 w-4" /> 已保存 {savedCount} 道错题
            </>
          ) : (
            <>
              <Save className="h-4 w-4" /> 确认保存 {wrongQuestions.length} 道错题
            </>
          )}
        </button>
        {error && (
          <span className="text-[12px] text-red-500">保存失败：{error}</span>
        )}
      </div>

      {croppedQuestion && imageSrcFor(croppedQuestion) && (
        <CropImageModal
          src={imageSrcFor(croppedQuestion)!}
          onCancel={() => setCropNumber(null)}
          onConfirm={(dataUrl) => {
            setImageUrls((prev) => ({ ...prev, [cropNumber!]: dataUrl }));
            setCropNumber(null);
          }}
        />
      )}
    </div>
  );
}
