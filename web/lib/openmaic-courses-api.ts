import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

/** 封面 slide 的最小结构（与 OpenMAIC /api/discover 返回的 canvas 对齐）。 */
export interface OpenMAICSlideTheme {
  backgroundColor?: string;
  fontColor?: string;
  fontName?: string;
  themeColors?: string[];
}

export interface OpenMAICSlideBackground {
  type?: "solid" | "image" | "gradient";
  color?: string;
  image?: string | { src?: string; size?: string };
  gradientColor?: string | string[];
}

export interface OpenMAICSlideElement {
  id?: string;
  type?: string;
  top?: number;
  left?: number;
  width?: number;
  height?: number;
  rotate?: number;
  /** 文字/公式等元素默认前景色 */
  color?: string;
  defaultColor?: string;
  defaultFontName?: string;
  defaultFontSize?: number;
  fill?: string;
  stroke?: string;
  opacity?: number;
  /** 文字在文本框内的垂直对齐 */
  vAlign?: "top" | "middle" | "bottom";
  lineHeight?: number;
  wordSpace?: number;
  align?: string;
  /** 形状：SVG viewBox / path */
  viewBox?: number[];
  path?: string;
  /** 形状是否保持宽高比（icon 类） */
  fixedRatio?: boolean;
  shadow?: { h: number; v: number; blur: number; color: string };
  /** text 元素：内联样式 HTML（font-size 等为视口 px） */
  content?: string;
  /** latex 元素：KaTeX 渲染好的 HTML */
  html?: string;
  /** latex 元素：LaTeX 源串（html 缺失时的兜底） */
  latex?: string;
  /** image 元素：绝对地址 */
  src?: string;
  poster?: string;
}

export interface OpenMAICSlideCover {
  id?: string;
  theme?: OpenMAICSlideTheme;
  background?: OpenMAICSlideBackground;
  elements?: OpenMAICSlideElement[];
  viewportSize?: number | number[] | { width?: number; height?: number };
  viewportRatio?: number;
}

/** OpenMAIC 公开课封面第一页 slide（canvas）。 */
export interface OpenMAICCourse {
  id: string;
  name: string;
  description?: string;
  updatedAt: number;
  publishedAt?: number;
  cover?: OpenMAICSlideCover;
  /** OpenMAIC 公开课页面（新标签页打开，免登录）。 */
  lesson_url: string;
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
