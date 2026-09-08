"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { ScoreBar, TrendIndicator } from "@/features/intelligence";

type Topic = { topic: string; authority: number; label: string; pages: number; queries: number; top10: number; coverage: number; momentum: number | null; opportunities: number };
type TopicDetail = { topic: string; authority_breakdown: Record<string, number>; strongest_pages: { url: string }[]; emerging_queries: { position: number }[]; weak_areas: { factor: string; score: number }[] };

export function TopicExplorer() {
  const [selected, setSelected] = useState<Topic | null>(null);
  const rows = useQuery({ queryKey: ["topics"], queryFn: () => api.get<{ topics: Topic[] }>("/topics?limit=200") });
  if (rows.isLoading) return <p className="text-sm text-[var(--muted)]">Carregando tópicos…</p>;
  if (rows.error) return <p className="text-sm text-[var(--danger)]">{(rows.error as ApiError).message}</p>;
  const topics = rows.data?.topics ?? [];
  return (
    <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]">
      <table className="w-full text-sm">
        <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]"><tr><th className="px-3 py-2">Tópico</th><th className="px-3 py-2">Authority</th><th className="px-3 py-2">Páginas</th><th className="px-3 py-2">Queries</th><th className="px-3 py-2">Top 10</th><th className="px-3 py-2">Cobertura</th><th className="px-3 py-2">Momentum</th><th className="px-3 py-2"><span className="sr-only">Abrir</span></th></tr></thead>
        <tbody>
          {topics.map((t) => <tr key={t.topic} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]"><td className="px-3 py-2 font-medium">{t.topic}</td><td className="px-3 py-2"><ScoreBar label="" score={t.authority} level={t.label} /></td><td className="px-3 py-2 tabular-nums">{t.pages}</td><td className="px-3 py-2 tabular-nums">{t.queries}</td><td className="px-3 py-2 tabular-nums">{t.top10}</td><td className="px-3 py-2 tabular-nums">{t.coverage}%</td><td className="px-3 py-2"><TrendIndicator deltaPct={t.momentum} /></td><td className="px-3 py-2 text-right"><Button size="sm" variant="secondary" onClick={() => setSelected(t)}>Abrir</Button></td></tr>)}
          {topics.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-[var(--muted)]">Nenhum tópico no topic graph.</td></tr>}
        </tbody>
      </table>
      {selected && <TopicDrawer topic={selected.topic} onClose={() => setSelected(null)} />}
    </div>
  );
}

function TopicDrawer({ topic, onClose }: { topic: string; onClose: () => void }) {
  const detail = useQuery({ queryKey: ["topic-detail", topic], queryFn: () => api.get<TopicDetail>(`/topics/detail?entity=${encodeURIComponent(topic)}`) });
  return (
    <Drawer title={`Tópico · ${topic}`} onClose={onClose}>
      {detail.isLoading && <p className="text-sm text-[var(--muted)]">Carregando…</p>}
      {detail.isError && <p className="text-sm text-[var(--danger)]">{(detail.error as ApiError).message}</p>}
      {detail.data && (
        <div className="space-y-4 text-sm">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Decomposição da autoridade</h3>
            <div className="mt-2 space-y-1.5">{Object.entries(detail.data.authority_breakdown).map(([k, v]) => <ScoreBar key={k} label={k} score={v} />)}</div>
          </div>
          {detail.data.weak_areas.length > 0 && <div><h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Pontos fracos</h3><ul className="mt-1 space-y-1">{detail.data.weak_areas.map((w) => <li key={w.factor} className="flex justify-between"><span>{w.factor}</span><Badge tone="warning">{w.score}%</Badge></li>)}</ul></div>}
          {detail.data.strongest_pages.length > 0 && <div><h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Páginas fortes</h3><ul className="mt-1 space-y-1">{detail.data.strongest_pages.map((p) => <li key={p.url} className="truncate text-[var(--muted)]">{p.url}</li>)}</ul></div>}
        </div>
      )}
    </Drawer>
  );
}
