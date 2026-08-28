"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus, type AuthStatus } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";

interface ProfileLinkProps {
  collapsed?: boolean;
}

export function ProfileLink({ collapsed = false }: ProfileLinkProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    fetchAuthStatus().then((next) => {
      // Surface the identity in both modes:
      //   • sync mode (auth on)   → the signed-in account,
      //   • local mode (auth off) → a "本地模式" badge linking to the
      //     storage settings where login / sync can be turned on.
      if (next?.authenticated) setStatus(next);
    });
  }, []);

  if (!status?.authenticated) return null;

  const isLocalMode = !status.enabled;
  const active = isLocalMode
    ? pathname.startsWith("/settings/storage")
    : pathname.startsWith("/profile");
  // Prefer the display nickname (XiaoZhi SSO), fall back to the username.
  const label = isLocalMode
    ? "本地模式"
    : status.nickname || status.username || "user";
  const href = isLocalMode ? "/settings/storage" : "/profile";
  const avatar = isLocalMode ? (
    <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-[var(--muted)] text-[10px]">
      ↺
    </span>
  ) : (
    <UserAvatar
      username={label}
      userId={status.user_id}
      avatar={status.avatar}
      role={status.role}
      size={collapsed ? 18 : 16}
    />
  );

  if (collapsed) {
    return (
      <Link
        href={href}
        className={`rounded-lg p-2 transition-colors
          ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
        aria-label={label}
        title={`${isLocalMode ? "本地模式 · 数据仅存本机" : t("My profile")} — ${label}`}
      >
        {avatar}
      </Link>
    );
  }

  return (
    <Link
      href={href}
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors
        ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        }`}
      title={isLocalMode ? "本地模式 · 数据仅存本机，登录可开启同步" : t("My profile")}
    >
      {avatar}
      <span className="truncate">{label}</span>
    </Link>
  );
}
