"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { ScoreBar, TrendIndicator } from "@/features/intelligence";

type Gap = { type: string; topic: string; competitors_covering: number; competitor_articles: number; our_coverage: number; gap_score: number; confidence: string; recommendation: string; label: string };
const GAP_LABEL: Record<string, string> = {
  missing_topic: "Conteúdo ausente", missing_subtopic: "Sub-tópico ausente",
  weak_coverage: "Cobertura fraca", outdated_coverage: "Conteúdo desatualizado",
  competitor_dominance: "Domínio do concorrente", cluster_gap: "Cluster incompleto",
  hub_gap: "Hub ausente", question_gap: "Pergunta não respondida",
};

export function ContentGaps() {
  const rows = useQuery({ queryKey: ["content-gaps"], queryFn: () => api.get<{ gaps: Gap[]; by_type: Record<string, number> }>("/content-gaps?as_percent=true") });
  if (rows.isLoading) return <p className="text-sm text-[var(--muted)]">Carregando lacunas…</p>;
  if (rows.error) return <p className="text-sm text-[var(--danger)]">{(rows.error as ApiError).message}</p>;
  const gaps = rows.data?.gaps ?? [];
  const byType = rows.data?.by_type ?? {};
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">{Object.entries(byType).map(([k, v]) => <Badge key={k} tone="warning">{GAP_LABEL[k] ?? k}: {v}</Badge>)}</div>
      <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]"><tr><th className="px-3 py-2">Lacuna</th><th className="px-3 py-2">Tópico</th><th className="px-3 py-2">Gap</th><th className="px-3 py-2">Score</th><th className="px-3 py-2">Concorrentes</th><th className="px-3 py-2">Nossa cobertura</th><th className="px-3 py-2">Confiança</th><th className="px-3 py-2">Recomendação</th></tr></thead>
          <tbody>
            {gaps.map((g) => <tr key={`${g.type}-${g.topic}`} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]"><td className="px-3 py-2"><Badge tone="warning">{GAP_LABEL[g.type] ?? g.type}</Badge></td><td className="px-3 py-2 font-medium">{g.topic}</td><td className="px-3 py-2 text-[var(--muted)]">{g.type}</td><td className="px-3 py-2 tabular-nums">{g.gap_score}</td><td className="px-3 py-2 tabular-nums">{g.competitors_covering} ({g.competitor_articles})</td><td className="px-3 py-2 tabular-nums">{g.our_coverage}</td><td className="px-3 py-2">{g.confidence}</td><td className="max-w-xs truncate px-3 py-2 text-[var(--muted)]">{g.recommendation}</td></tr>)}
            {gaps.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma lacuna. Rode o competitor-corpus primeiro (CLI: competitor-crawl).</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
