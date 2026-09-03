"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, BookOpenCheck, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import OpenMAICWatchPlayer from "@/components/openmaic/OpenMAICWatchPlayer";
import {
  listOpenMAICCourses,
  type OpenMAICCourse,
} from "@/lib/openmaic-courses-api";

/**
 * OpenMAIC 课件播放页：从发现列表按 id 定位课程，内嵌 watch 播放器。
 * 课程不在公开列表（未发布/已删除）时给出返回提示。
 */
export default function OpenMAICCoursePlayerSection() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const courseId = String(params.id || "");
  const [course, setCourse] = useState<OpenMAICCourse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;
    void listOpenMAICCourses({ force: true })
      .then((rows) => {
        if (!cancelled) {
          setCourse(rows.find((c) => c.id === courseId) ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setCourse(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const backLink = (
    <Link
      href="/space/openmaic"
      className="text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline"
    >
      {t("openmaic.backToDiscover")}
    </Link>
  );

  if (loading) {
    return (
      <div>
        <SpaceSectionHeader icon={BookOpenCheck} title={t("openmaic.loading")} description="" action={backLink} />
        <div className="flex items-center justify-center py-16 text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      </div>
    );
  }

  if (!course) {
    return (
      <div>
        <SpaceSectionHeader icon={BookOpenCheck} title={t("openmaic.notFound")} description="" action={backLink} />
        <p className="text-[13px] text-[var(--muted-foreground)]">
          {t("openmaic.notFoundHint")}
        </p>
      </div>
    );
  }

  return (
    <div>
      <SpaceSectionHeader icon={BookOpenCheck} title={course.name} description="" action={backLink} />
      <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
        <div className="aspect-video w-full">
          <OpenMAICWatchPlayer src={course.watch_url} />
        </div>
      </div>
    </div>
  );
}
