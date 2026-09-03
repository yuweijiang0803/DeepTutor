"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowUpRight,
  BookOpenCheck,
  Circle,
  CircleCheck,
  CircleDot,
  CirclePlay,
  FlaskConical,
  Layers,
  Lightbulb,
  ListOrdered,
  Loader2,
  Puzzle,
  RefreshCcw,
  Rocket,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  getSubject,
  type SubjectDetail,
  type SubjectKnowledgePoint,
} from "@/lib/subjects-api";
import {
  fetchAllProgress,
  fetchMasteryMap,
  initFromSubject,
  type MasteryMapResult,
  type ObjectiveStatus,
} from "@/lib/learning-api";
import { newMasteryPathChatUrl } from "@/lib/chat-launch-intent";

/** 知识点类型 → 小图标 + i18n key。 */
const KP_META: Record<string, { icon: LucideIcon; label: string }> = {
  memory: { icon: Lightbulb, label: "knowledgeType.memory" },
  procedure: { icon: ListOrdered, label: "knowledgeType.procedure" },
  concept: { icon: Puzzle, label: "knowledgeType.concept" },
  design: { icon: FlaskConical, label: "knowledgeType.design" },
};

/** 掌握度状态视觉，与 /space/learning 的 PathMap 保持一致。 */
const STATUS_META: Record<ObjectiveStatus, { icon: LucideIcon; className: string }> = {
  mastered: { icon: CircleCheck, className: "text-green-500" },
  learning: { icon: CircleDot, className: "text-yellow-500" },
  new: { icon: Circle, className: "text-[var(--muted-foreground)]" },
};

function kpIcon(kp: SubjectKnowledgePoint) {
  const fallback = KP_META.concept;
  return KP_META[kp.kp_type] ?? fallback;
}

function KnowledgePointCard({
  kp,
  status,
}: {
  kp: SubjectKnowledgePoint;
  /** null = 尚未建精通之路，无掌握度数据。 */
  status?: ObjectiveStatus | null;
}) {
  const { t } = useTranslation();
  const meta = kpIcon(kp);
  const Icon = meta.icon;
  const StatusIcon = status ? STATUS_META[status].icon : null;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-3 py-2.5">
      <span
        aria-hidden
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-teal-500/10 text-teal-600 dark:text-teal-400"
      >
        <Icon size={14} strokeWidth={1.7} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {status && StatusIcon ? (
            <StatusIcon
              size={13}
              strokeWidth={1.8}
              className={`shrink-0 ${STATUS_META[status].className}`}
            />
          ) : null}
          <p className="truncate text-[13px] font-medium text-[var(--foreground)]">
            {kp.name}
          </p>
        </div>
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
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const params = useParams<{ subjectId: string }>();
  const subjectId = String(params.subjectId || "");
  const [subject, setSubject] = useState<SubjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  /** null = 正在探测该学科是否已有精通之路 path。 */
  const [pathExists, setPathExists] = useState<boolean | null>(null);
  const [mastery, setMastery] = useState<MasteryMapResult | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(() => {
    if (!subjectId) return;
    setLoading(true);
    setError("");
    setPathExists(null);
    setMastery(null);
    void getSubject(subjectId, { force: true })
      .then(setSubject)
      .catch(() => setError(t("subjects.loadError")))
      .finally(() => setLoading(false));
    // 探测该学科是否已有精通之路 path。走只读的 fetchAllProgress（按
    // book_id 匹配），避免 fetchProgress 的 get_or_create 副作用创建空 path。
    void fetchAllProgress()
      .then(async (result) => {
        const hasPath = result.summaries.some(
          (s) => s.book_id === subjectId && s.kp_count > 0,
        );
        setPathExists(hasPath);
        if (hasPath) {
          try {
            setMastery(await fetchMasteryMap(subjectId));
          } catch {
            setMastery(null);
          }
        }
      })
      .catch(() => setPathExists(false));
  }, [subjectId, t]);

  useEffect(load, [load]);

  /** kp_id → 掌握度状态，用于目录树上的状态徽标。 */
  const kpStatus = useMemo(() => {
    const index = new Map<string, ObjectiveStatus>();
    for (const module of mastery?.map.modules ?? [])
      for (const kp of module.knowledge_points) index.set(kp.id, kp.status);
    return index;
  }, [mastery]);

  const startLearning = useCallback(async () => {
    if (!subjectId || starting) return;
    setStarting(true);
    try {
      if (pathExists === false) {
        await initFromSubject(subjectId, subjectId);
        setPathExists(true);
      }
      router.push(newMasteryPathChatUrl(subjectId));
    } catch {
      setError(t("subjects.startError"));
      setStarting(false);
    }
  }, [subjectId, pathExists, starting, router, t]);

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

  const masteryCounts = mastery?.map.counts;
  const masteryPct = masteryCounts?.total
    ? Math.round((masteryCounts.mastered / masteryCounts.total) * 100)
    : 0;

  return (
    <div>
      <SpaceSectionHeader
        icon={BookOpenCheck}
        title={subject.name}
        description={`${meta} · ${subject.modules.length} ${t("subjects.chapters")} · ${totalKps} ${t("subjects.knowledgePoints")}`}
        action={
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/space/subjects"
              className="text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline"
            >
              {t("subjects.all")}
            </Link>
            <button
              type="button"
              onClick={startLearning}
              disabled={pathExists === null || starting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {starting ? (
                <Loader2 size={14} strokeWidth={1.8} className="animate-spin" />
              ) : pathExists ? (
                <ArrowUpRight size={14} strokeWidth={1.8} />
              ) : (
                <Rocket size={14} strokeWidth={1.8} />
              )}
              {starting
                ? t("subjects.preparing")
                : pathExists
                  ? t("subjects.continue")
                  : t("subjects.start")}
            </button>
          </div>
        }
      />

      {masteryCounts && masteryCounts.total > 0 ? (
        <div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <span className="text-[13px] text-[var(--muted-foreground)]">
              {masteryCounts.mastered}/{masteryCounts.total} {t("subjects.mastered")}
              {masteryCounts.learning > 0 ? (
                <>
                  {" · "}
                  {masteryCounts.learning} {t("subjects.learning")}
                </>
              ) : null}
            </span>
            <span className="text-[13px] font-semibold tabular-nums text-[var(--foreground)]">
              {masteryPct}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--accent)]">
            <div
              className="h-full rounded-full bg-green-500 transition-all"
              style={{ width: `${masteryPct}%` }}
            />
          </div>
        </div>
      ) : null}

      <div className="space-y-6">
        {subject.modules.map((module) => (
          <section key={module.id}>
            <h2 className="mb-2.5 flex items-center gap-2 text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
              <Layers size={15} strokeWidth={1.7} className="text-[var(--muted-foreground)]" />
              {module.name}
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {module.knowledge_points.map((kp) => (
                <KnowledgePointCard
                  key={kp.id}
                  kp={kp}
                  status={kpStatus.get(kp.id) ?? null}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
