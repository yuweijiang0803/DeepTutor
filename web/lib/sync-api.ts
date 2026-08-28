"use client";

import { apiFetch, apiUrl } from "@/lib/api";

export interface SyncStatus {
  mode: "local" | "dual" | "mysql";
  synced: boolean;
  host?: string;
}

export interface SyncReport {
  sessions: number;
  turns: number;
  messages: number;
  events: number;
  notebook_entries: number;
  mastery_paths: number;
}

export interface SyncEnableResponse {
  mode: "dual";
  already_enabled?: boolean;
  report?: SyncReport;
}

export interface SyncDisableResponse {
  mode: "local";
  already_disabled?: boolean;
  report?: SyncReport | null;
}

export interface MySqlConnectionInput {
  host: string;
  port?: number;
  user?: string;
  password?: string;
  database?: string;
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(apiUrl("/api/v1/sync/status"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`sync status failed: ${res.status}`);
  return res.json();
}

export async function enableSync(
  mysql: MySqlConnectionInput,
): Promise<SyncEnableResponse> {
  const res = await apiFetch("/api/v1/sync/enable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mysql }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? "enable sync failed");
  }
  return res.json();
}

export async function disableSync(
  pullFirst = false,
): Promise<SyncDisableResponse> {
  const res = await apiFetch("/api/v1/sync/disable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pull_first: pullFirst }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? "disable sync failed");
  }
  return res.json();
}
