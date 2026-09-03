"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  BookOpenCheck,
  CirclePlay,
  FlaskConical,
  Layers,
  Lightbulb,
  ListOrdered,
  Puzzle,
  RefreshCcw,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  getSubject,
  type SubjectDetail,
  type SubjectKnowledgePoint,
} from "@/lib/subjects-api";

/** 知识点类型 → 小图标 + i18n key。 */
const KP_META: Record<string, { icon: LucideIcon; label: string }> = {
  memory: { icon: Lightbulb, label: "knowledgeType.memory" },
  procedure: { icon: ListOrdered, label: "knowledgeType.procedure" },
  concept: { icon: Puzzle, label: "knowledgeType.concept" },
  design: { icon: FlaskConical, label: "knowledgeType.design" },
};

function kpIcon(kp: SubjectKnowledgePoint) {
  const fallback = KP_META.concept;
  return KP_META[kp.kp_type] ?? fallback;
}

function KnowledgePointCard({ kp }: { kp: SubjectKnowledgePoint }) {
  const { t } = useTranslation();
  const meta = kpIcon(kp);
  const Icon = meta.icon;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-3 py-2.5">
      <span
        aria-hidden
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-teal-500/10 text-teal-600 dark:text-teal-400"
      >
        <Icon size={14} strokeWidth={1.7} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-[var(--foreground)]">
          {kp.name}
        </p>
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {t(meta.label)}
          {kp.questions.length > 0
            ? ` · ${kp.questions.length} ${t("questions.suffix")}`
            : ""}
        </p>
      </div>
      {kp.openmaic_url ? (
        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-orange-500/10 px-2 py-1 text-[11px] font-medium text-orange-600 dark:text-orange-400">
          <CirclePlay size={12} strokeWidth={1.8} />
          {t("subjects.playable")}
        </span>
      ) : (
        <span className="shrink-0 rounded-md bg-[var(--muted)]/50 px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
          {t("subjects.pending")}
        </span>
      )}
    </div>
  );
}

/**
 * 学科详情：章 → 知识点 目录树（教材对齐的预置内容）。
 * 知识点卡片显示类型与题库数量；OpenMAIC 课件生成后展示"可播放"状态。
 */
export default function SubjectDetailSection() {
  const { t } = useTranslation();
  const params = useParams<{ subjectId: string }>();
  const subjectId = String(params.subjectId || "");
  const [subject, setSubject] = useState<SubjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!subjectId) return;
    setLoading(true);
    setError("");
    getSubject(subjectId, { force: true })
      .then(setSubject)
      .catch(() => setError(t("subjects.loadError")))
      .finally(() => setLoading(false));
  }, [subjectId, t]);

  useEffect(load, [load]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-9 w-56 animate-pulse rounded-xl bg-[var(--muted)]/40" />
        <div className="h-5 w-96 animate-pulse rounded bg-[var(--muted)]/40" />
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-[140px] animate-pulse rounded-xl border border-[var(--border)] bg-[var(--muted)]/30"
          />
        ))}
      </div>
    );
  }

  if (error || !subject) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-10 text-center">
        <p className="text-[14px] text-[var(--muted-foreground)]">{error || t("subjects.notFound")}</p>
        <Link
          href="/space/subjects"
          className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--foreground)] hover:underline"
        >
          <RefreshCcw size={13} strokeWidth={1.8} />
          {t("subjects.backToCatalog")}
        </Link>
      </div>
    );
  }

  const meta = [
    subject.stage === "junior"
      ? t("subjects.stage.junior")
      : subject.stage === "senior"
        ? t("subjects.stage.senior")
        : subject.stage === "primary"
          ? t("subjects.stage.primary")
          : subject.stage,
    subject.grade,
    subject.textbook,
  ]
    .filter(Boolean)
    .join(" · ");

  const totalKps = subject.modules.reduce(
    (sum, m) => sum + m.knowledge_points.length,
    0,
  );

  return (
    <div>
      <SpaceSectionHeader
        icon={BookOpenCheck}
        title={subject.name}
        description={`${meta} · ${subject.modules.length} ${t("subjects.chapters")} · ${totalKps} ${t("subjects.knowledgePoints")}`}
        action={
          <Link
            href="/space/subjects"
            className="text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline"
          >
            {t("subjects.all")}
          </Link>
        }
      />
      <div className="space-y-6">
        {subject.modules.map((module) => (
          <section key={module.id}>
            <h2 className="mb-2.5 flex items-center gap-2 text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
              <Layers size={15} strokeWidth={1.7} className="text-[var(--muted-foreground)]" />
              {module.name}
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {module.knowledge_points.map((kp) => (
                <KnowledgePointCard key={kp.id} kp={kp} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
