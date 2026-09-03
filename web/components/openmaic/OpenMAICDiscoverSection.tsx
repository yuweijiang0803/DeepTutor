"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { BookOpenCheck, Loader2, Play } from "lucide-react";
import { useTranslation } from "react-i18next";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import OpenMAICSlideCover from "@/components/openmaic/OpenMAICSlideCover";
import {
  listOpenMAICCourses,
  type OpenMAICCourse,
} from "@/lib/openmaic-courses-api";

function CourseCard({ course }: { course: OpenMAICCourse }) {
  const cover = course.cover;
  return (
    <Link
      href={`/space/openmaic/${course.id}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
    >
      {/* 封面：真实 cover 用轻量渲染器画出第一页；无 cover 时用占位 */}
      <div className="relative w-full overflow-hidden bg-[#eef2ff]">
        {cover ? (
          <OpenMAICSlideCover cover={cover} />
        ) : (
          <div className="flex aspect-video w-full items-center justify-center px-4">
            <span className="text-center text-[13px] text-[var(--muted-foreground)]">
              {course.name}
            </span>
          </div>
        )}
        <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-[var(--foreground)]/90 text-[var(--background)] opacity-0 transition-opacity group-hover:opacity-100">
          <Play size={12} strokeWidth={2} className="ml-0.5" />
        </span>
      </div>
      <div className="flex-1 px-3 py-2.5">
        <p className="truncate text-[13.5px] font-medium text-[var(--foreground)]">
          {course.name}
        </p>
      </div>
    </Link>
  );
}

/**
 * OpenMAIC 课件发现列表：展示 OpenMAIC 已发布(public)的 AI 讲解课件，
 * 点击进入内嵌播放页。
 */
export default function OpenMAICDiscoverSection() {
  const { t } = useTranslation();
  const [courses, setCourses] = useState<OpenMAICCourse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void listOpenMAICCourses({ force: true })
      .then((rows) => {
        if (!cancelled) setCourses(rows);
      })
      .catch(() => {
        /* empty state below */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const body = useMemo(() => {
    if (loading) {
      return (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="aspect-[16/11] animate-pulse rounded-xl border border-[var(--border)] bg-[var(--muted)]/40"
            />
          ))}
        </div>
      );
    }
    if (courses.length === 0) {
      return (
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t("openmaic.discoverEmpty")}
        </p>
      );
    }
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
        {courses.map((course) => (
          <CourseCard key={course.id} course={course} />
        ))}
      </div>
    );
  }, [loading, courses, t]);

  return (
    <div>
      <SpaceSectionHeader
        icon={BookOpenCheck}
        title={t("openmaic.discoverTitle")}
        description={t("openmaic.discoverDescription")}
      />
      {body}
    </div>
  );
}
