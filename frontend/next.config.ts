import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Mesma origem (ADR-0004): /api/v1 vai para a FastAPI/ transporte stdlib.
    return [
      { source: "/api/v1/:path*", destination: `${process.env.API_URL || "http://127.0.0.1:8000"}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
