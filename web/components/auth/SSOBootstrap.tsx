"use client";

import { useEffect } from "react";
import { ssoAutoLogin } from "@/lib/auth";
import { notifyAuthStatusChanged } from "@/hooks/useAuthStatus";

/**
 * 根布局级自动登录引导（对齐 OpenMAIC 的 SsoBootstrap）。
 *
 * 页面加载时探测 manager 统一登录 cookie（``mix-token``）——后端 /sso 校验通过
 * 就直接建立 DeepTutor 会话，然后通知所有 useAuthStatus 消费者刷新身份。进程内
 * 只跑一次；软导航不重复触发。
 */
let started = false;

export function SSOBootstrap() {
  useEffect(() => {
    if (started) return;
    started = true;
    // URL ?token=（manager 深链跳转带 token）时一并传给后端。
    const urlToken =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("token") ?? undefined
        : undefined;
    ssoAutoLogin(urlToken).then((status) => {
      if (status) notifyAuthStatusChanged();
    });
  }, []);

  return null;
}
