import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

/** OpenMAIC 公开课封面第一页 slide（canvas）。首版仅用于标题/配色摘要。 */
export interface OpenMAICCourse {
  id: string;
  name: string;
  description?: string;
  updatedAt: number;
  publishedAt?: number;
  cover?: {
    theme?: { backgroundColor?: string };
    elements?: { type: string; content?: string }[];
  };
  /** OpenMAIC watch 播放页地址（DeepTutor 内嵌 iframe 用）。 */
  watch_url: string;
}

/** 从 cover 首屏提取标题文本（首个 text element 的纯文本）。 */
export function coverTitle(course: OpenMAICCourse): string {
  const elements = course.cover?.elements ?? [];
  for (const el of elements) {
    if (el.type === "text" && el.content) {
      return el.content.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    }
  }
  return "";
}

/** 封面占位背景色：优先取 slide theme，缺省用蓝色渐变。 */
export function coverBackground(course: OpenMAICCourse): string {
  return course.cover?.theme?.backgroundColor ?? "#eef2ff";
}

export async function listOpenMAICCourses(options?: {
  force?: boolean;
}): Promise<OpenMAICCourse[]> {
  return withClientCache<OpenMAICCourse[]>(
    "openmaic:discover",
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/openmaic/discover"), {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Failed to fetch OpenMAIC courses: ${response.status}`);
      const payload = (await response.json()) as {
        base_url?: string;
        courses?: OpenMAICCourse[];
      };
      return payload.courses ?? [];
    },
    { force: options?.force, ttlMs: 30_000 },
  );
}

export function invalidateOpenMAICCourses(): void {
  invalidateClientCache("openmaic:");
}
