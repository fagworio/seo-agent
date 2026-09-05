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
    // URL absoluta explícita a partir dos headers do proxy (x-forwarded-*).
    // NÃO usar req.nextUrl.clone(): com `next start -H 127.0.0.1 -p 3100` o
    // Next serializa o origin como localhost:3100, ignorando o Host header.
    const host =
      req.headers.get("x-forwarded-host") ||
      req.headers.get("host") ||
      "seo.unicorniohater.com.br";
    // Esquema decidido pelo host: domínio real => https (HSTS/CF cuidam do resto);
    // loopback => http (dev local). Não confiar em x-forwarded-proto: proxies
    // intermediários podem mandar "http" mesmo com cliente em https.
    const isLoopback = host.startsWith("localhost") || host.startsWith("127.");
    const proto = isLoopback ? "http" : "https";
    const url = new URL(`/login?from=${encodeURIComponent(pathname)}`, `${proto}://${host}`);
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
    "/improvements",
    "/experiments",
    "/integrations",
    "/activity",
    "/settings/:path*",
  ],
};
