"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { LogIn } from "lucide-react";
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
    fetchAuthStatus().then(setStatus);
  }, []);

  // Auth off (local storage, no login required yet): show a sign-in entry
  // point — unless a real account is already signed in (ready to enable sync),
  // in which case show the account below.
  if (
    status &&
    !status.enabled &&
    !(status.authenticated && status.username && status.username !== "local")
  ) {
    const href = `/login?redirect=${encodeURIComponent("/settings/storage")}`;
    if (collapsed) {
      return (
        <Link
          href={href}
          className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          aria-label="登录"
          title="登录（开启同步）"
        >
          <LogIn size={18} strokeWidth={1.5} />
        </Link>
      );
    }
    return (
      <Link
        href={href}
        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        title="登录后可开启同步"
      >
        <LogIn size={16} strokeWidth={1.5} />
        <span>登录</span>
      </Link>
    );
  }

  if (!status?.authenticated || !status?.username) return null;

  const active = pathname.startsWith("/profile");
  // Prefer the display nickname (XiaoZhi SSO), fall back to the username.
  const label = status.nickname || status.username;
  const avatar = (
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
        href="/profile"
        className={`rounded-lg p-2 transition-colors
          ${
            active
              ? "bg-[var(--primary)]/10 text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          }`}
        aria-label={t("My profile")}
        title={`${t("My profile")} — ${label}`}
      >
        {avatar}
      </Link>
    );
  }

  return (
    <Link
      href="/profile"
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors
        ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
        }`}
      title={t("My profile")}
    >
      {avatar}
      <span className="truncate">{label}</span>
    </Link>
  );
}
