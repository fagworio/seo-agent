"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError, PageSummary } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Input } from "@/design-system/input";
import { Pagination } from "@/components/pagination";
import { ScoreBar, ScoreBadge, TrendIndicator } from "@/features/intelligence";

const PAGE_SIZE = 20;
const PRESETS = [
  ["", "Todos"],
  ["high_potential", "Alto potencial"],
  ["near_top10", "Quase Top 10"],
  ["technical_block", "Bloqueio técnico"],
] as const;

export default function PagesPage() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("captured");
  const [preset, setPreset] = useState("");
  const [page, setPage] = useState(1);
  const offset = (page - 1) * PAGE_SIZE;
  const { data, error, isLoading } = useQuery({
    queryKey: ["pages", q, sort, page],
    queryFn: () => api.get<{ pages?: PageSummary[]; total?: number }>(
      `/pages?limit=${PAGE_SIZE}&offset=${offset}&sort=${sort}&q=${encodeURIComponent(q)}&include_rankability_v2=true`),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;
  const pages = (data?.pages ?? []).filter((p) => presetFilter(p, preset));
  const total = data?.total ?? 0;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-xl font-semibold">Páginas</h1><p className="mt-1 text-sm text-[var(--muted)]">SEO Page Explorer — posição, rankability, headroom, autoridade e oportunidade de cada URL.</p></div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-56"><Input aria-label="Buscar URL" placeholder="Buscar URL…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
          <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={preset} onChange={(e) => { setPreset(e.target.value); setPage(1); }} aria-label="Filtro">
            {PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} aria-label="Ordenar">
            <option value="captured">Mais recente</option>
            <option value="clicks">Mais cliques</option>
            <option value="position">Melhor posição</option>
            <option value="title">Título</option>
          </select>
        </div>
      </div>

      <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
            <tr>
              <th className="px-3 py-2">Página</th>
              <th className="px-3 py-2">Pos.</th>
              <th className="px-3 py-2">Cliques</th>
              <th className="px-3 py-2">Rankability</th>
              <th className="px-3 py-2">Headroom</th>
              <th className="px-3 py-2">Autoridade</th>
              <th className="px-3 py-2">Tendência</th>
              <th className="px-3 py-2">Oportunidade</th>
              <th className="px-3 py-2">Estado</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((item) => {
              const v2 = item.rankability_v2;
              return (
                <tr key={item.url} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
                  <td className="max-w-xs truncate px-3 py-2">
                    <Link href={`/pages/${encodeURIComponent(item.url)}`} className="text-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
                      {item.title || item.url}
                    </Link>
                    <span className="block truncate text-xs text-[var(--muted)]">{item.url}</span>
                  </td>
                  <td className="px-3 py-2 tabular-nums">{String(item.metrics.position ?? "—")}</td>
                  <td className="px-3 py-2 tabular-nums">{item.metrics.clicks}</td>
                  <td className="px-3 py-2"><ScoreBadge score={v2?.topic_authority?.score} label="Rank" /></td>
                  <td className="px-3 py-2 tabular-nums">{scoreCell(v2?.headroom?.score)}</td>
                  <td className="px-3 py-2 tabular-nums">{scoreCell(v2?.topic_authority?.score)}</td>
                  <td className="px-3 py-2"><TrendIndicator deltaPct={momentumOf(v2)} /></td>
                  <td className="px-3 py-2"><ScoreBadge score={v2?.opportunity?.score} label="Oport" /></td>
                  <td className="px-3 py-2"><Badge tone={item.index_state === "noindex" ? "danger" : "neutral"}>{item.index_state}</Badge></td>
                </tr>
              );
            })}
            {pages.length === 0 && (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma página capturada.</td></tr>
            )}
          </tbody>
        </table>
        <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} label="páginas" />
      </div>
    </div>
  );
}

function presetFilter(p: PageSummary, preset: string): boolean {
  if (!preset) return true;
  const opp = p.rankability_v2?.opportunity?.score ?? 0;
  const pos = p.metrics.position ?? null;
  if (preset === "high_potential") return opp >= 70;
  if (preset === "near_top10") return pos != null && pos > 10 && pos <= 20;
  if (preset === "technical_block") return p.index_state === "noindex" || p.health === "error";
  return true;
}
function scoreCell(v?: number | null) { return typeof v === "number" ? Math.round(v) : "—"; }
function momentumOf(v?: { signals?: { momentum_delta_pct?: number | null } } | null) { return v?.signals?.momentum_delta_pct ?? null; }
