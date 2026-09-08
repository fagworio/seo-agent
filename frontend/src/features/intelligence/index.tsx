"use client";

import { Badge } from "@/design-system/badge";
import { classify, type Factor, type IntelligenceScore } from "./contract";

/** Barra compacta de score (tem levado em conta nao so a cor). */
export function ScoreBar({ label, score, level }: { label: string; score?: number | null; level?: string }) {
  const cls = classify(score);
  const width = typeof score === "number" ? Math.max(0, Math.min(100, score)) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-36 shrink-0 text-[var(--muted)]">{label}</span>
      <span className="w-8 text-right tabular-nums">{typeof score === "number" ? Math.round(score) : "—"}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--surface-raised)]" aria-hidden>
        <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${width}%` }} />
      </div>
      <span className="w-24 shrink-0 text-xs text-[var(--muted)]">{level ? levelLabel(level) : cls.label}</span>
    </div>
  );
}

function levelLabel(level: string): string {
  const map: Record<string, string> = { muito_baixo: "Muito baixo", baixo: "Baixo", moderado: "Moderado", alto: "Alto", muito_alto: "Muito alto" };
  return map[level] ?? classifyLabel(level);
}
function classifyLabel(level: string): string { return level.replace(/_/g, " "); }

/** Badge compacto de score + nivel. */
export function ScoreBadge({ score, label }: { score?: number | null; label?: string }) {
  const cls = classify(score);
  return <Badge tone={cls.tone} title={cls.label}>{label ?? "Score"}: {typeof score === "number" ? Math.round(score) : "—"}</Badge>;
}

/** ConfidenceBadge (alta/média/baixa). */
export function ConfidenceBadge({ score, label }: { score?: number | null; label?: string }) {
  const lvl = (label || "").toLowerCase();
  const tone = lvl.includes("alta") || lvl === "high" ? "success" : lvl.includes("média") || lvl === "medium" ? "info" : "warning";
  const pct = typeof score === "number" ? `${Math.round(score * 100)}%` : "—";
  return <Badge tone={tone} title={`Confiança: ${pct}`}>Confiança {label ? `${label} · ${pct}` : pct}</Badge>;
}

/** Ícone/texto de tendência (↑↓→). */
export function TrendIndicator({ deltaPct, className = "" }: { deltaPct?: number | null; className?: string }) {
  if (deltaPct == null) return <span className={className}>→</span>;
  if (deltaPct > 0) return <span className={className}>↑ {Math.round(deltaPct)}%</span>;
  if (deltaPct < 0) return <span className={className}>↓ {Math.abs(Math.round(deltaPct))}%</span>;
  return <span className={className}>→</span>;
}

/** Decomposição de um score: lista de factors com barra curta. */
export function ScoreBreakdown({ title, score, level, factors }: { title: string; score?: number; level?: string; factors?: Factor[] }) {
  const cls = classify(score);
  return (
    <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">{title}</h3>
        <Badge tone={cls.tone}>{typeof score === "number" ? Math.round(score) : "—"} <span className="ml-1">{level ?? cls.label}</span></Badge>
      </div>
      {factors && factors.length > 0
        ? <div className="mt-3 space-y-1.5">{factors.map((f) => <ScoreBar key={f.key ?? f.label} label={f.label} score={f.value} />)}</div>
        : <p className="mt-3 text-sm text-[var(--muted)]">Sem fatores disponíveis.</p>}
    </div>
  );
}

/** Bloco resumo de inteligência (Rankability/Headroom/Authority/Opportunity). */
export function IntelligenceScores({ scores }: { scores: { rankability?: IntelligenceScore; headroom?: number | null; topicAuthority?: number | null; opportunity?: IntelligenceScore; confidence?: { score?: number; label?: string } } }) {
  const room = typeof scores.headroom === "number" ? scores.headroom : null;
  return (
    <div className="grid gap-3">
      {typeof scores.topicAuthority === "number" && <ScoreBar label="Topic Authority" score={scores.topicAuthority} />}
      {scores.rankability && typeof scores.rankability.score === "number" && <ScoreBar label="Rankability" score={scores.rankability.score} level={scores.rankability.level as string} />}
      <ScoreBar label="Headroom" score={room} />
      {scores.confidence && <div><ConfidenceBadge score={scores.confidence.score as number} label={scores.confidence.label} /></div>}
      {scores.opportunity && typeof scores.opportunity.score === "number" && <ScoreBar label="Oportunidade" score={scores.opportunity.score} level={scores.opportunity.level as string} />}
    </div>
  );
}

/** F14 — estado de dados ausentes/incompletos (nunca mostrar "0" como dado). */
export function MissingData({ label = "Dados indisponíveis", detail }: { label?: string; detail?: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border)] px-4 py-3 text-sm">
      <span className="text-[var(--muted)]">—</span>
      <span className="ml-2 font-medium">{label}</span>
      {detail && <p className="mt-1 text-xs text-[var(--muted)]">{detail}</p>}
    </div>
  );
}
