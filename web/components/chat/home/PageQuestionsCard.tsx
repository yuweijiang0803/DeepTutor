"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Loader2, Save } from "lucide-react";
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

  const handleSave = async () => {
    setSaving(true);
    setError("");
    let count = 0;
    try {
      for (const q of wrongQuestions) {
        const image = q.image_data_url
          ? [
              {
                base64: q.image_data_url.split(",")[1] ?? "",
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
          return (
            <button
              key={q.number}
              onClick={() => toggle(q.number)}
              className={`rounded-lg border p-2 text-left transition-colors ${
                wrong
                  ? "border-red-500/50 bg-red-500/5"
                  : "border-[var(--border)] bg-[var(--background)]/50"
              }`}
              title={q.text}
            >
              {q.image_data_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={q.image_data_url}
                  alt={`第${q.number}题`}
                  className="max-h-40 w-full rounded-md object-contain bg-white"
                />
              ) : (
                <div className="flex h-24 items-center justify-center text-[12px] text-[var(--muted-foreground)]">
                  {q.text || `第${q.number}题`}
                </div>
              )}
              <div className="mt-2 flex items-center justify-between px-1">
                <span className="text-[12px] text-[var(--muted-foreground)]">
                  第{q.number}题
                </span>
                <span
                  className={`flex items-center gap-1 text-[12px] ${
                    wrong ? "text-red-500" : "text-[var(--muted-foreground)]"
                  }`}
                >
                  <CheckCircle2 size={13} />
                  {wrong ? "错题" : "不是错题"}
                </span>
              </div>
            </button>
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
    </div>
  );
}
