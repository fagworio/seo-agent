import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// O nome do cookie depende do modo (see ADR-0003): __Host-seo_session (HTTPS,
// Secure) ou seo_session (HTTP local). O middleware aceita ambos; a autorização
// REAL é enforced server-side no backend /api/v1 (deny-by-default), nunca na UI.
const PUBLIC = ["/login", "/forgot-password", "/reset-password"];
const COOKIES = ["__Host-seo_session", "seo_session"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();
  if (!COOKIES.some((c) => req.cookies.has(c))) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/today",
    "/work",
    "/pages/:path*",
    "/agents/:path*",
    "/technical",
    "/editorial",
    "/experiments",
    "/integrations",
    "/activity",
    "/settings",
  ],
};
