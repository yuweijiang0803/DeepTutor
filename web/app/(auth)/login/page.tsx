"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { login, fetchAuthStatus, xiaozhiLogin } from "@/lib/auth";

/** Read a cookie value (non-HttpOnly cookies only). */
function getCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

/** Clear a cookie set on this host (path=/). */
function clearCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
}

// Set by /logout. When present, the login page must NOT auto-SSO — the user
// explicitly signed out and the shared mix-token would otherwise log them
// straight back in. Cleared on the next explicit sign-in.
const LOGGED_OUT_COOKIE = "dt_logged_out";

function LoginPageContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSso, setCheckingSso] = useState(true);

  // 1. 检测已登录 / 小智 SSO 登录态；都没有则停在账号密码表单
  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (status?.authenticated) {
        clearCookie(LOGGED_OUT_COOKIE);
        router.replace(next);
        return;
      }
      // 用户刚点过退出 → 不自动 SSO
      if (getCookie(LOGGED_OUT_COOKIE)) {
        setCheckingSso(false);
        return;
      }
      const mixToken = getCookie("mix-token");
      if (mixToken) {
        xiaozhiLogin(mixToken).then((result) => {
          if (result.ok) {
            clearCookie(LOGGED_OUT_COOKIE);
            router.replace(next);
          } else {
            setCheckingSso(false);
          }
        });
      } else {
        setCheckingSso(false);
      }
    });
  }, [router, next]);

  // 2. 在小智平台登录后（mix-token 出现且用户未主动退出）自动进入
  useEffect(() => {
    if (checkingSso) return;
    const id = setInterval(() => {
      if (getCookie(LOGGED_OUT_COOKIE)) return;
      const mixToken = getCookie("mix-token");
      if (!mixToken) return;
      clearInterval(id);
      xiaozhiLogin(mixToken).then((result) => {
        if (result.ok) {
          clearCookie(LOGGED_OUT_COOKIE);
          router.replace(next);
        }
      });
    }, 3000);
    return () => clearInterval(id);
  }, [checkingSso, router, next]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    const result = await login(username, password);

    if (result.ok) {
      clearCookie(LOGGED_OUT_COOKIE);
      router.replace(next);
    } else {
      setError(result.error ?? t("Login failed"));
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      {/* Logo / Title */}
      <div className="text-center mb-8">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          DeepTutor
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("Sign in to your account")}
        </p>
      </div>

      {/* Card */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-sm px-8 py-8">
        {checkingSso ? (
          <p className="text-center text-sm text-[var(--muted-foreground)] py-4">
            Checking sign-in…
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Account */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
              >
                {t("Email or username")}
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                           bg-[var(--background)] text-[var(--foreground)]
                           placeholder:text-[var(--muted-foreground)]
                           focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                           transition-shadow text-sm"
                placeholder="you@example.com"
              />
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
              >
                {t("Password")}
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-lg border border-[var(--border)]
                           bg-[var(--background)] text-[var(--foreground)]
                           placeholder:text-[var(--muted-foreground)]
                           focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
                           transition-shadow text-sm"
                placeholder="••••••••"
              />
            </div>

            {/* Error */}
            {error && (
              <p className="text-sm text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 rounded-lg font-medium text-sm
                         bg-[var(--primary)] text-[var(--primary-foreground)]
                         hover:opacity-90 active:opacity-80
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-opacity"
            >
              {loading ? t("Signing in…") : t("Sign in")}
            </button>
          </form>
        )}
      </div>

      <p className="mt-3 text-center text-xs text-[var(--muted-foreground)]">
        DeepTutor · Agent-Native Learning
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="w-full max-w-sm text-center text-sm text-[var(--muted-foreground)]">
          Loading sign in...
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
