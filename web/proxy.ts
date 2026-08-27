import { NextRequest, NextResponse } from "next/server";
import { parseAuthEnabled } from "./lib/api";
import {
  CODEX_CALLBACK_API_PATH,
  COOKIE_NAME,
  LOGIN_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isCodexCallbackPath,
} from "./lib/proxy-policy";

// Backend base URL for `/api/*` and `/ws/*` rewrites. The container entrypoint
// exports `DEEPTUTOR_API_BASE_URL` from `data/user/settings/system.json`
// (preferring `next_public_api_base`, then `next_public_api_base_external`,
// then `http://127.0.0.1:${BACKEND_PORT}`). This last-resort default applies
// only when nothing exported the variable at all.
//
// The loopback is spelled as the IPv4 literal, not `localhost`: on a dual-stack
// host that name resolves to ::1 first, while uvicorn binds 0.0.0.0 (IPv4
// only), so every rewrite would fail to connect.
const API_BASE_URL =
  process.env.DEEPTUTOR_API_BASE_URL ?? "http://127.0.0.1:8001";

const AUTH_ENABLED = parseAuthEnabled(process.env.DEEPTUTOR_AUTH_ENABLED);

// LOCAL_MODE: the backend serves local (non-synced) installations without
// login. The auth gate must mirror that decision at the edge, but the storage
// mode flips at runtime (a user can enable sync mid-session), so it is polled
// from the backend rather than baked into the build. Short TTL keeps the cost
// to one request per few seconds at most.
let _modeCache: { mode: "local" | "sync"; at: number } | null = null;

async function backendStorageMode(): Promise<"local" | "sync"> {
  const now = Date.now();
  if (_modeCache && now - _modeCache.at < 5000) return _modeCache.mode;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/sync/status`, {
      cache: "no-store",
    });
    const data = (await res.json()) as { mode?: string };
    _modeCache = { mode: data.mode === "sync" ? "sync" : "local", at: now };
  } catch {
    _modeCache = { mode: "local", at: now };
  }
  return _modeCache.mode;
}

// Redirect to the login page, preserving the intended destination in `next`.
// A present-but-invalid cookie is cleared so the browser stops resending it;
// when no cookie was sent there is nothing to clear.
function redirectToLogin(
  req: NextRequest,
  { clearCookie }: { clearCookie: boolean },
): NextResponse {
  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = LOGIN_PATH;
  loginUrl.searchParams.set("next", req.nextUrl.pathname);
  const response = NextResponse.redirect(loginUrl);
  if (clearCookie) response.cookies.delete(COOKIE_NAME);
  return response;
}

export async function proxy(req: NextRequest): Promise<NextResponse> {
  const { pathname, search } = req.nextUrl;

  if (isCodexCallbackPath(pathname)) {
    return NextResponse.rewrite(
      new URL(CODEX_CALLBACK_API_PATH + search, API_BASE_URL),
    );
  }

  // 1. Bridge the origin gap: forward backend-relative paths to the API server.
  //    This keeps the URL knowledge in one place (the entrypoint + system.json)
  //    rather than baked into the frontend bundle.
  if (isBackendPath(pathname)) {
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL));
  }

  // 2. Auth gate — multi-user mode only. Disabled by default, and never blocks
  //    auth pages, Next.js internals, or public static assets (see
  //    isAuthExempt: that exemption is what keeps the logo/banner images
  //    loading once login is enabled — issue #599).
  if (!AUTH_ENABLED || isAuthExempt(pathname)) {
    return NextResponse.next();
  }

  // LOCAL_MODE: local (non-synced) installations need no login at the edge.
  if ((await backendStorageMode()) === "local") {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (classifyToken(token, Date.now()) !== "valid") {
    return redirectToLogin(req, { clearCookie: Boolean(token) });
  }

  return NextResponse.next();
}

export const config = {
  // Run on every request except Next.js internals and the favicon. The /api/*
  // and /ws/* paths are explicitly handled above (rewritten to the backend);
  // large knowledge create/upload requests are handled by dedicated App Router
  // endpoints that stream directly to FastAPI. Excluding them here is crucial:
  // merely entering Proxy makes Next clone and cap the multipart body.
  // the browser's /_next/image optimizer requests are excluded here, while the
  // optimizer's loopback fetch for the source image (e.g. /logo.png) is let
  // through the auth gate by isAuthExempt.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/v1/knowledge/(?:create|[^/]+/upload)(?:/|$)).*)",
  ],
};
