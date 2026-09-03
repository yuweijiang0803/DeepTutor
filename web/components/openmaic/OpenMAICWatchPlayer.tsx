"use client";

/**
 * OpenMAICWatchPlayer — 在 DeepTutor 里 iframe 嵌入 OpenMAIC 讲解播放页，
 * 并监听 postMessage 拿"当前播放页上下文"（供学生提问时注入 agent）。
 *
 * OpenMAIC 讲解播放页（/watch/<classroomId>）在场景切换时会 postMessage：
 *   { type:'openmaic:scene', stageId, sceneIndex, sceneCount,
 *     sceneType, title, text, speech }
 */
import { useEffect, useState } from "react";
import {
  setOpenMAICPlaybackContext,
  type OpenMAICSceneContext,
} from "@/lib/openmaic-playback";

// Re-export so callers (e.g. the openmaic-test page) can import the context
// type from this component rather than reaching into the store module.
export type { OpenMAICSceneContext };

export default function OpenMAICWatchPlayer({
  src,
  onSceneChange,
  className,
}: {
  /** OpenMAIC 讲解播放页地址，如 https://learn.hourofai.cn/watch/<id> */
  src: string;
  /** 场景切换回调（父组件可用它记录学情/注入聊天上下文） */
  onSceneChange?: (ctx: OpenMAICSceneContext) => void;
  className?: string;
}) {
  const [current, setCurrent] = useState<OpenMAICSceneContext | null>(null);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const data = e.data;
      if (
        data &&
        typeof data === "object" &&
        (data as { type?: string }).type === "openmaic:scene"
      ) {
        const ctx: OpenMAICSceneContext = {
          stageId: (data as { stageId?: string }).stageId,
          sceneIndex: (data as { sceneIndex: number }).sceneIndex,
          sceneCount: (data as { sceneCount: number }).sceneCount,
          sceneType: (data as { sceneType?: string }).sceneType,
          title: (data as { title?: string }).title,
          text: (data as { text?: string }).text,
          speech: (data as { speech?: string }).speech,
        };
        setCurrent(ctx);
        setOpenMAICPlaybackContext(ctx);
        onSceneChange?.(ctx);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [onSceneChange]);

  return (
    <div className={className ?? "w-full h-full"}>
      <iframe
        src={src}
        className="w-full h-full border-0"
        allow="autoplay; microphone; fullscreen"
        sandbox="allow-scripts allow-same-origin allow-presentation allow-forms allow-popups"
      />
    </div>
  );
}
