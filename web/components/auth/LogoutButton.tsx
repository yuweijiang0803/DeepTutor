"use client";

import { LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";
import { logout } from "@/lib/auth";
import { useAuthStatus } from "@/hooks/useAuthStatus";

interface LogoutButtonProps {
  collapsed?: boolean;
}

export function LogoutButton({ collapsed = false }: LogoutButtonProps) {
  const { t } = useTranslation();
  const { authenticated } = useAuthStatus();

  // Sign-out only makes sense when actually signed in — an anonymous visitor
  // gets the "登录" entry (ProfileLink) instead, never both at once.
  if (!authenticated) return null;

  async function handleLogout() {
    await logout();
    // Clear the session server-side + cookie, then reload so every consumer
    // (sidebar, profile, send gate) re-reads the logged-out state. Stays on
    // the current page — the reload re-renders the same route.
    window.location.reload();
  }

  if (collapsed) {
    return (
      <button
        onClick={handleLogout}
        className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
        aria-label={t("Sign out")}
        title={t("Sign out")}
      >
        <LogOut size={16} strokeWidth={1.5} />
      </button>
    );
  }

  return (
    <button
      onClick={handleLogout}
      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
    >
      <LogOut size={16} strokeWidth={1.5} />
      <span>{t("Sign out")}</span>
    </button>
  );
}
