"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError, PageSummary } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Input } from "@/design-system/input";

export default function PagesPage() {
  const [q, setQ] = useState("");
  const { data, error, isLoading } = useQuery({
    queryKey: ["pages", q],
    queryFn: () => api.get<{ pages: PageSummary[] }>(`/pages?limit=100&q=${encodeURIComponent(q)}`),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  return (
    <div className="space-y-4">
      <div className="flex max-w-md items-center gap-2">
        <Input placeholder="Buscar URL…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
            <tr>
              <th className="px-3 py-2">Página</th>
              <th className="px-3 py-2">Saúde</th>
              <th className="px-3 py-2">Posição</th>
              <th className="px-3 py-2">Cliques</th>
              <th className="px-3 py-2">Indexar</th>
            </tr>
          </thead>
          <tbody>
            {data!.pages.map((page) => (
              <tr key={page.url} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
                <td className="max-w-lg truncate px-3 py-2">
                  <Link href={`/pages/${encodeURIComponent(page.url)}`} className="text-[var(--primary)]">
                    {page.title || page.url}
                  </Link>
                  <span className="block truncate text-xs text-[var(--muted)]">{page.url}</span>
                </td>
                <td className="px-3 py-2"><HealthBadge health={page.health} /></td>
                <td className="px-3 py-2 tabular-nums">{String(page.metrics.position ?? "—")}</td>
                <td className="px-3 py-2 tabular-nums">{page.metrics.clicks}</td>
                <td className="px-3 py-2"><Badge tone={page.index_state === "noindex" ? "danger" : "neutral"}>{page.index_state}</Badge></td>
              </tr>
            ))}
            {data!.pages.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma página capturada.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HealthBadge({ health }: { health: string }) {
  const tone = health === "ok" ? "success" : health === "error" ? "danger" : health === "redirect" ? "warning" : "neutral";
  return <Badge tone={tone}>{health}</Badge>;
}
