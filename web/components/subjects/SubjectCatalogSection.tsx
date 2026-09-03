"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { BookOpenCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { listSubjects, type SubjectSummary } from "@/lib/subjects-api";

/**
 * 学科目录区块：列出教材对齐的学科包（数学/语文/英语…）。
 * 每个学科显示 学段/册/教材 元信息与 章·知识点 计数，点击进入详情树。
 */
export default function SubjectCatalogSection() {
  const { t } = useTranslation();
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void listSubjects({ force: true })
      .then((rows) => {
        if (!cancelled) setSubjects(rows);
      })
      .catch(() => {
        /* leave empty list — section renders the empty state */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stageLabel = useCallback(
    (stage: string): string => {
      if (stage === "junior") return t("subjects.stage.junior");
      if (stage === "senior") return t("subjects.stage.senior");
      if (stage === "primary") return t("subjects.stage.primary");
      return stage;
    },
    [t],
  );

  const body = useMemo(() => {
    if (loading) {
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="h-[104px] animate-pulse rounded-xl border border-[var(--border)] bg-[var(--muted)]/40"
            />
          ))}
        </div>
      );
    }
    if (subjects.length === 0) {
      return (
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t("subjects.empty")}
        </p>
      );
    }
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {subjects.map((subject) => {
          const meta = [stageLabel(subject.stage), subject.grade, subject.textbook]
            .filter(Boolean)
            .join(" · ");
          return (
            <Link
              key={subject.id}
              href={`/space/subjects/${subject.id}`}
              className="group flex flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
            >
              <div className="flex items-start gap-3">
                <span
                  aria-hidden
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-orange-500/10 text-orange-600 dark:text-orange-400"
                >
                  <BookOpenCheck size={18} strokeWidth={1.7} />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-[14.5px] font-medium leading-tight tracking-tight text-[var(--foreground)]">
                    {subject.name}
                  </h3>
                  <p className="mt-0.5 truncate text-[12px] text-[var(--muted-foreground)]">
                    {meta}
                  </p>
                </div>
              </div>
              <p className="mt-3 flex items-baseline gap-3 text-[12.5px] text-[var(--muted-foreground)]">
                <span>
                  <span className="font-semibold tabular-nums text-[var(--foreground)]">
                    {subject.module_count}
                  </span>{" "}
                  {t("subjects.chapters")}
                </span>
                <span>
                  <span className="font-semibold tabular-nums text-[var(--foreground)]">
                    {subject.kp_count}
                  </span>{" "}
                  {t("subjects.knowledgePoints")}
                </span>
              </p>
            </Link>
          );
        })}
      </div>
    );
  }, [loading, subjects, stageLabel, t]);

  return (
    <div>
      <SpaceSectionHeader
        icon={BookOpenCheck}
        title={t("subjects.title")}
        description={t("subjects.catalogDescription")}
      />
      {body}
    </div>
  );
}
