/**
 * OpenMAIC 讲解播放上下文（全局，当前标签页内共享）。
 *
 * 课程页里的讲解播放器（OpenMAICWatchPlayer）在场景切换时写入这里；
 * 聊天发消息时（lib/unified-ws.ts 的 send）把最近一次播放上下文拼进用户消息，
 * 让 agent 知道学生"正在看哪一页、看了什么内容"，从而结合当前页精准答疑。
 */

export type OpenMAICSceneContext = {
  stageId?: string;
  sceneIndex: number;
  sceneCount: number;
  sceneType?: string;
  title?: string;
  text?: string;
  speech?: string;
};

const FRESH_MS = 10 * 60 * 1000; // 上下文 10 分钟内有效

let current: (OpenMAICSceneContext & { ts: number }) | null = null;

export function setOpenMAICPlaybackContext(ctx: OpenMAICSceneContext | null): void {
  current = ctx ? { ...ctx, ts: Date.now() } : null;
}

export function clearOpenMAICPlaybackContext(): void {
  current = null;
}

/**
 * 返回要拼进用户消息的播放上下文前缀；无有效上下文时返回空串。
 */
export function buildOpenMAICPlaybackPrefix(): string {
  if (!current) return "";
  if (Date.now() - current.ts > FRESH_MS) return "";
  const parts: string[] = [];
  parts.push(`第 ${current.sceneIndex + 1}/${current.sceneCount} 页`);
  if (current.title) parts.push(`标题「${current.title}」`);
  if (current.text) parts.push(`页面内容：${current.text}`);
  if (current.speech) parts.push(`讲解词：${current.speech}`);
  return `[学生正在观看 AI 讲解，${parts.join("，")}]`;
}
