"use client";

/**
 * 讲解播放 iframe 桥接测试页：
 *   iframe 嵌 OpenMAIC 讲解播放页 + 实时显示 postMessage 拿到的"当前播放上下文"
 *   用法：/openmaic-test?url=http://localhost:3000/watch/<classroomId>
 */
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import OpenMAICWatchPlayer, {
  type OpenMAICSceneContext,
} from "@/components/openmaic/OpenMAICWatchPlayer";

function TestInner() {
  const params = useSearchParams();
  const url =
    params.get("url") || "http://localhost:3000/watch/iZ_tpMaYaK";
  const [ctx, setCtx] = useState<OpenMAICSceneContext | null>(null);

  return (
    <div className="h-screen flex flex-col bg-white">
      <div className="shrink-0 p-2 bg-gray-100 border-b flex items-center gap-2">
        <span className="text-xs font-semibold text-gray-600">OpenMAIC iframe 桥接测试</span>
        <span className="text-xs text-gray-400 font-mono truncate">{url}</span>
      </div>
      <div className="flex-1 min-h-0">
        <OpenMAICWatchPlayer
          src={url}
          onSceneChange={setCtx}
          className="w-full h-full"
        />
      </div>
      <div className="shrink-0 p-3 border-t bg-gray-50 text-xs max-h-56 overflow-auto">
        <div className="font-semibold mb-1 text-gray-700">当前播放上下文（postMessage）</div>
        <pre className="whitespace-pre-wrap font-mono text-gray-600">
          {ctx ? JSON.stringify(ctx, null, 2) : "(尚未收到 — 在 iframe 里翻页试试)"}
        </pre>
      </div>
    </div>
  );
}

export default function OpenMAICTestPage() {
  return (
    <Suspense fallback={<div className="p-4">加载中…</div>}>
      <TestInner />
    </Suspense>
  );
}
