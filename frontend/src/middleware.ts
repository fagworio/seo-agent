import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Sem a sessão server-side verificável no edge, o middleware é apenas um gate
// de UX: redireciona para /login sem o cookie. A autorização REAL é enforced
// server-side no backend /api/v1 (deny-by-default), nunca na UI.
const PUBLIC = ["/login"];
const COOKIE = "__Host-seo_session";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();
  if (!req.cookies.has(COOKIE)) {
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
