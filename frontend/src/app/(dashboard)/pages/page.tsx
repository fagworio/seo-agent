"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError, PageSummary } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Input } from "@/design-system/input";
import { Pagination } from "@/components/pagination";

const PAGE_SIZE = 20;

export default function PagesPage() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("captured");
  const [page, setPage] = useState(1);
  const offset = (page - 1) * PAGE_SIZE;
  const { data, error, isLoading } = useQuery({
    queryKey: ["pages", q, sort, page],
    queryFn: () => api.get<{ pages: PageSummary[]; total: number }>(
      `/pages?limit=${PAGE_SIZE}&offset=${offset}&sort=${sort}&q=${encodeURIComponent(q)}`),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;
  const pages = data!.pages;
  const total = data!.total;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-xl font-semibold">Páginas</h1><p className="mt-1 text-sm text-[var(--muted)]">Estado atual, visibilidade orgânica e prioridade de cada URL.</p></div>
        <div className="flex items-end gap-2">
          <div className="w-56"><Input aria-label="Buscar URL" placeholder="Buscar URL…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
          <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} aria-label="Ordenar">
            <option value="captured">Mais recente</option>
            <option value="clicks">Mais cliques</option>
            <option value="position">Melhor posição</option>
            <option value="title">Título</option>
          </select>
        </div>
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
            {pages.map((item) => (
              <tr key={item.url} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
                <td className="max-w-lg truncate px-3 py-2">
                  <Link href={`/pages/${encodeURIComponent(item.url)}`} className="text-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
                    {item.title || item.url}
                  </Link>
                  <span className="block truncate text-xs text-[var(--muted)]">{item.url}</span>
                </td>
                <td className="px-3 py-2"><HealthBadge health={item.health} /></td>
                <td className="px-3 py-2 tabular-nums">{String(item.metrics.position ?? "—")}</td>
                <td className="px-3 py-2 tabular-nums">{item.metrics.clicks}</td>
                <td className="px-3 py-2"><Badge tone={item.index_state === "noindex" ? "danger" : "neutral"}>{item.index_state}</Badge></td>
              </tr>
            ))}
            {pages.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma página capturada.</td></tr>
            )}
          </tbody>
        </table>
        <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} label="páginas" />
      </div>
    </div>
  );
}

function HealthBadge({ health }: { health: string }) {
  const tone = health === "ok" ? "success" : health === "error" ? "danger" : health === "redirect" ? "warning" : "neutral";
  return <Badge tone={tone}>{health}</Badge>;
}
