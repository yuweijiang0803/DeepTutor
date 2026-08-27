"use client";

import { useCallback, useEffect, useState } from "react";
import { CloudOff, CloudUpload, Database, Loader2, LogIn } from "lucide-react";

import { SettingsPageHeader } from "@/components/settings/shared";
import { fetchAuthStatus } from "@/lib/auth";
import {
  disableSync,
  enableSync,
  fetchSyncStatus,
  type SyncReport,
  type SyncStatus,
} from "@/lib/sync-api";

type Busy = "none" | "enabling" | "disabling";

export default function StorageSettingsPage() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<Busy>("none");
  const [error, setError] = useState("");
  const [report, setReport] = useState<SyncReport | null>(null);
  const [pullFirst, setPullFirst] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchSyncStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    fetchAuthStatus()
      .then((s) => setLoggedIn(Boolean(s?.authenticated ?? s)))
      .catch(() => setLoggedIn(false));
  }, [refresh]);

  const isSync = status?.mode === "sync";

  const handleEnable = async () => {
    setBusy("enabling");
    setError("");
    setReport(null);
    try {
      const res = await enableSync({ host: "" }); // connection is pre-provisioned server-side
      setReport(res.report ?? null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("none");
    }
  };

  const handleDisable = async () => {
    setBusy("disabling");
    setError("");
    setReport(null);
    try {
      const res = await disableSync(pullFirst);
      setReport(res.report ?? null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("none");
    }
  };

  const loginHref = `/login?redirect=${encodeURIComponent("/settings/storage")}`;

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title="数据存储"
        description="数据保存在本机（默认），或同步到学校服务器（需 XiaoZhi 账号）"
      />

      {/* Mode card */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
        <div className="flex items-start gap-3">
          <Database className="mt-0.5 h-5 w-5 text-[var(--muted-foreground)]" />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-[15px] font-semibold">
                {isSync ? "云端同步模式" : "本地模式"}
              </h3>
              <span
                className={
                  "rounded-full px-2 py-0.5 text-[11px] " +
                  (isSync
                    ? "bg-emerald-500/10 text-emerald-500"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)]")
                }
              >
                {isSync ? "Sync" : "Local"}
              </span>
            </div>
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {isSync
                ? `数据保存在服务器${status?.host ? `（${status.host}）` : ""}，
                  可跨设备访问，教师/家长可查看学情。`
                : "会话、错题、精通路径都只保存在本机，无需登录。"}
            </p>
          </div>
        </div>

        {/* Report / error */}
        {report && (
          <div className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-[12px] text-emerald-500">
            迁移完成：{report.sessions} 会话 · {report.messages} 消息 ·{" "}
            {report.notebook_entries} 错题 · {report.mastery_paths} 精通路径
          </div>
        )}
        {error && (
          <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/5 px-4 py-3 text-[12px] text-red-500">
            {error}
          </div>
        )}
      </div>

      {/* Local mode: enable-sync card */}
      {!isSync && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
          <div className="flex items-center gap-2">
            <CloudUpload className="h-4 w-4 text-[var(--muted-foreground)]" />
            <h3 className="text-[14px] font-semibold">开启同步</h3>
          </div>
          <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
            登录 XiaoZhi 账号后，把本地数据上传到学校服务器。之后的新数据会直接存入服务器。
            服务器连接已由学校统一配置，无需手动填写。
          </p>

          {loggedIn === false && (
            <a
              href={loginHref}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-[13px] font-medium text-[var(--accent-foreground)]"
            >
              <LogIn className="h-4 w-4" /> 先登录 XiaoZhi 账号
            </a>
          )}
          {loggedIn === null && (
            <div className="mt-4 flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> 检查登录状态…
            </div>
          )}

          {loggedIn === true && (
            <button
              onClick={handleEnable}
              disabled={busy !== "none"}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-[13px] font-medium text-[var(--accent-foreground)] disabled:opacity-50"
            >
              {busy === "enabling" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> 正在上传…
                </>
              ) : (
                <>
                  <CloudUpload className="h-4 w-4" /> 开启同步并上传本地数据
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Sync mode: disable card */}
      {isSync && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
          <div className="flex items-center gap-2">
            <CloudOff className="h-4 w-4 text-[var(--muted-foreground)]" />
            <h3 className="text-[14px] font-semibold">关闭同步</h3>
          </div>
          <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
            回到本地模式，之后数据只保存在本机。服务器上的数据默认保留，可勾选拉回。
          </p>
          <label className="mt-4 flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={pullFirst}
              onChange={(e) => setPullFirst(e.target.checked)}
            />
            把服务器上的数据拉回本地再关闭
          </label>
          <button
            onClick={handleDisable}
            disabled={busy !== "none"}
            className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-500/40 px-4 py-2 text-[13px] font-medium text-red-500 disabled:opacity-50"
          >
            {busy === "disabling" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> 正在处理…
              </>
            ) : (
              "关闭同步"
            )}
          </button>
        </div>
      )}
    </div>
  );
}
