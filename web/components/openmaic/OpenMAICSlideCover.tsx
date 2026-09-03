"use client";

/**
 * OpenMAICSlideCover — 在 DeepTutor 里把 OpenMAIC 封面的第一张 slide
 * （canvas JSON）缩略渲染出来，观感与 OpenMAIC 首页「发现」一致。
 *
 * 做法与 OpenMAIC 相同：不把封面存成图片，而是按 slide 的原始坐标
 * （viewport px）逐元素排版，再把整层按容器宽度等比缩小。元素类型覆盖
 * 这类 AI 讲解课件封面常见的内容：文字 / 形状(SVG path) / latex(KaTeX
 * HTML) / 图片(绝对地址)。图表、视频等元素在缩略图上不渲染。
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type {
  OpenMAICSlideBackground,
  OpenMAICSlideCover,
  OpenMAICSlideElement,
  OpenMAICSlideTheme,
} from "@/lib/openmaic-courses-api";

import "./openmaic-slide-cover.css";

const DEFAULT_WIDTH = 1000;
const DEFAULT_RATIO = 0.5625; // 16:9

/** 去掉内容 HTML 里可能夹带的脚本 / 事件属性（封面内容来自远端课件）。 */
function sanitizeHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, "");
}

function viewportOf(cover: OpenMAICSlideCover): { width: number; height: number } {
  const vs = cover.viewportSize;
  let width = DEFAULT_WIDTH;
  if (typeof vs === "number") {
    width = vs > 0 ? vs : DEFAULT_WIDTH;
  } else if (Array.isArray(vs)) {
    const n = Number(vs[0]);
    width = n > 0 ? n : DEFAULT_WIDTH;
  } else if (vs && typeof vs === "object") {
    const n = Number(vs.width);
    width = n > 0 ? n : DEFAULT_WIDTH;
  }
  const ratio = Number(cover.viewportRatio) > 0 ? Number(cover.viewportRatio) : DEFAULT_RATIO;
  return { width, height: Math.round(width * ratio) };
}

function backgroundStyle(
  background: OpenMAICSlideBackground | undefined,
  theme: OpenMAICSlideTheme | undefined,
): CSSProperties {
  const themeColor = theme?.backgroundColor || "#ffffff";
  if (!background) return { backgroundColor: themeColor };
  if (background.type === "image") {
    const src =
      typeof background.image === "string"
        ? background.image
        : background.image?.src;
    if (src) {
      return {
        backgroundImage: `url("${src}")`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      };
    }
    return { backgroundColor: themeColor };
  }
  if (background.type === "gradient") {
    const colors = Array.isArray(background.gradientColor)
      ? background.gradientColor
      : background.gradientColor
        ? [background.gradientColor]
        : [];
    if (colors.length > 1) {
      return { backgroundImage: `linear-gradient(135deg, ${colors.join(", ")})` };
    }
  }
  return { backgroundColor: background.color || themeColor };
}

/** 元素公用外框：原始坐标。旋转由各元素内部处理（统一绕中心）。 */
function elementBoxStyle(el: OpenMAICSlideElement): CSSProperties {
  return {
    position: "absolute",
    top: el.top ?? 0,
    left: el.left ?? 0,
    width: el.width ?? 0,
    height: el.height ?? 0,
    opacity: el.opacity,
  };
}

function shadowStyle(el: OpenMAICSlideElement): CSSProperties | undefined {
  const shadow = el.shadow;
  if (!shadow) return undefined;
  const value = `${shadow.h}px ${shadow.v}px ${shadow.blur}px ${shadow.color}`;
  return el.type === "text" ? { textShadow: value } : { boxShadow: value };
}

function SlideText({
  el,
  theme,
}: {
  el: OpenMAICSlideElement;
  theme: OpenMAICSlideTheme | undefined;
}) {
  const vAlign = el.vAlign ?? "top";
  const justifyContent =
    vAlign === "middle" ? "center" : vAlign === "bottom" ? "flex-end" : "flex-start";
  const content = sanitizeHtml(el.content || "");
  const color = el.defaultColor || el.color || theme?.fontColor || "#333333";
  const fontFamily = el.defaultFontName || theme?.fontName || undefined;
  return (
    <div style={elementBoxStyle(el)}>
      <div
        style={{
          width: "100%",
          height: "100%",
          transform: `rotate(${el.rotate ?? 0}deg)`,
          backgroundColor: el.fill,
          display: "flex",
          flexDirection: "column",
          justifyContent,
        }}
      >
        <div
          className="slide-text"
          style={{
            position: "relative",
            boxSizing: "border-box",
            width: "100%",
            padding: "10px",
            overflowWrap: "break-word",
            color,
            fontFamily,
            lineHeight: el.lineHeight,
            letterSpacing:
              el.wordSpace !== undefined ? `${el.wordSpace}px` : undefined,
            ...shadowStyle(el),
          }}
          dangerouslySetInnerHTML={{ __html: content }}
        />
      </div>
    </div>
  );
}

function SlideShape({
  el,
}: {
  el: OpenMAICSlideElement;
}) {
  const viewBox = Array.isArray(el.viewBox) && el.viewBox.length >= 2 ? el.viewBox : [1, 1];
  const fixedRatio = Boolean(el.fixedRatio);
  const fill = el.fill || "#5b9bd5";
  return (
    <div style={elementBoxStyle(el)}>
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${viewBox[0]} ${viewBox[1]}`}
        preserveAspectRatio={fixedRatio ? "xMidYMid meet" : "none"}
        style={{
          display: "block",
          overflow: "visible",
          transform: `rotate(${el.rotate ?? 0}deg)`,
          transformOrigin: "center",
        }}
      >
        <path d={el.path || ""} fill={fill} stroke={el.stroke} />
      </svg>
    </div>
  );
}

function SlideLatex({
  el,
}: {
  el: OpenMAICSlideElement;
}) {
  const color = el.color || "#333333";
  const align = el.align;
  const html = el.html ? sanitizeHtml(el.html) : "";
  return (
    <div
      style={{
        ...elementBoxStyle(el),
        display: "flex",
        flexDirection: "column",
        justifyContent: align === "center" ? "center" : "flex-start",
        alignItems: align === "center" ? "center" : "flex-start",
        color,
        transform: `rotate(${el.rotate ?? 0}deg)`,
      }}
    >
      {html ? (
        <span dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <span style={{ fontStyle: "italic", fontFamily: "serif", fontSize: 18 }}>
          {el.latex || ""}
        </span>
      )}
    </div>
  );
}

function SlideImage({
  el,
}: {
  el: OpenMAICSlideElement;
}) {
  const src =
    typeof el.src === "string" && /^https?:\/\//.test(el.src) ? el.src : "";
  if (!src) return null;
  return (
    <div style={elementBoxStyle(el)}>
      {/* eslint-disable-next-line @next/next/no-img-element -- 封面内联缩略图，按 slide 布局裁剪，无需 next/image 优化 */}
      <img
        src={src}
        alt=""
        draggable={false}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          transform: `rotate(${el.rotate ?? 0}deg)`,
          transformOrigin: "center",
        }}
      />
    </div>
  );
}

function renderElement(el: OpenMAICSlideElement, theme: OpenMAICSlideTheme | undefined) {
  switch (el.type) {
    case "text":
      return <SlideText key={el.id ?? "text"} el={el} theme={theme} />;
    case "shape":
      return <SlideShape key={el.id ?? "shape"} el={el} />;
    case "latex":
      return <SlideLatex key={el.id ?? "latex"} el={el} />;
    case "image":
      return <SlideImage key={el.id ?? "image"} el={el} />;
    default:
      return null; // chart / video / table / line 等在封面缩略图上从略
  }
}

export default function OpenMAICSlideCover({
  cover,
  className,
}: {
  cover: OpenMAICSlideCover;
  className?: string;
}) {
  const vp = useMemo(() => viewportOf(cover), [cover]);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(0);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const update = () => {
      if (node.clientWidth > 0) setScale(node.clientWidth / vp.width);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [vp]);

  const theme = cover.theme;
  return (
    <div
      ref={rootRef}
      className={`omc-slide-cover relative w-full overflow-hidden ${className ?? ""}`}
      style={{ aspectRatio: `${vp.width} / ${vp.height}` }}
      aria-hidden
    >
      {/* 背景 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          ...backgroundStyle(cover.background, theme),
        }}
      />
      {/* slide 内容层：按原始视口 px 排版，再整体缩放到容器宽度 */}
      {scale > 0 ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: vp.width,
            height: vp.height,
            transformOrigin: "top left",
            transform: `scale(${scale})`,
          }}
        >
          {(cover.elements ?? []).map((el) => renderElement(el, theme))}
        </div>
      ) : null}
    </div>
  );
}
