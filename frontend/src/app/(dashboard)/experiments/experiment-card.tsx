"use client";

import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";
import type { Experiment } from "@/lib/api";

/** Card de um experimento/intervenção implementada (comparação observacional). */
export function ExperimentCard({ experiment }: { experiment: Experiment }) {
  const baseline = metricGroup(experiment.baseline, "gsc");
  const current = metricGroup(experiment.current, "gsc");
  const delta = metricGroup(experiment.delta, "gsc");
  return <Card title={experiment.keyword || experiment.url || "Intervenção sem título"}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><Badge tone={stateTone(experiment.measurement_state)}>{stateLabel(experiment.measurement_state)}</Badge>{experiment.verdict && <Badge tone={verdictTone(experiment.verdict)}>{verdictLabel(experiment.verdict)}</Badge>}</div>
    <dl className="space-y-1 text-sm"><Row label="Intervenção" value={experiment.implemented_action || experiment.opportunity_type || "Não informada"} /><Row label="Implementada em" value={experiment.implemented_at || "Não informada"} /><Row label="Página" value={experiment.url || "Não informada"} /></dl>
    <div className="mt-4 overflow-x-auto rounded-md border border-[var(--border)]"><table className="w-full text-sm"><thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]"><tr><th className="px-3 py-2">Métrica</th><th className="px-3 py-2">Antes</th><th className="px-3 py-2">Atual</th><th className="px-3 py-2">Variação observada</th></tr></thead><tbody><MetricRow label="Cliques" before={baseline.clicks} after={current.clicks} delta={delta.clicks_delta} /><MetricRow label="Impressões" before={baseline.impressions} after={current.impressions} delta={delta.impressions_delta} /><MetricRow label="Posição média" before={baseline.position} after={current.position} delta={delta.position_delta} decimals /></tbody></table></div>
    {!Object.keys(current).length && <p className="mt-3 rounded-md border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted)]">A janela atual ainda não possui dados comparáveis. Isso não significa resultado zero.</p>}
    <div className="mt-3 flex flex-wrap gap-2 text-xs">{Object.entries(experiment.windows ?? {}).map(([window, measured]) => <Badge key={window} tone={measured ? "success" : "neutral"}>{window}: {measured ? "medido" : "aguardando"}</Badge>)}</div>
    {experiment.limitations
      ? <p className="mt-3 text-xs text-[var(--muted)]">Qualidade da medição: {experiment.limitations}</p>
      : <p className="mt-3 text-xs text-[var(--muted)]">Qualidade da medição: comparação observacional entre janelas; sazonalidade e outras alterações podem influenciar o resultado.</p>}
  </Card>;
}

function metricGroup(parent: Record<string, unknown> | undefined, key: string): Record<string, unknown> { const value = parent?.[key]; return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function numeric(value: unknown): number | null { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function MetricRow({ label, before, after, delta, decimals = false }: { label: string; before: unknown; after: unknown; delta: unknown; decimals?: boolean }) { const values = [before, after, delta].map(numeric); const format = (value: number | null, signed = false) => value === null ? "—" : `${signed && value > 0 ? "+" : ""}${value.toLocaleString("pt-BR", { maximumFractionDigits: decimals ? 1 : 0 })}`; return <tr className="border-t border-[var(--border)]"><th className="px-3 py-2 text-left font-medium">{label}</th><td className="px-3 py-2 tabular-nums">{format(values[0])}</td><td className="px-3 py-2 tabular-nums">{format(values[1])}</td><td className="px-3 py-2 tabular-nums">{format(values[2], true)}</td></tr>; }
function Row({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">{label}</dt><dd className="max-w-[65%] break-words text-right">{value}</dd></div>; }
function stateLabel(value: string) { return ({ measured: "Resultado medido", measuring: "Medição em andamento", waiting_data: "Aguardando dados" } as Record<string, string>)[value] ?? value; }
function verdictLabel(value: string) { return ({ improved: "Melhora observada", worsened: "Piora observada", neutral: "Sem mudança relevante" } as Record<string, string>)[value] ?? value; }
function stateTone(value: string): "success" | "warning" | "info" | "neutral" { if (value === "measured") return "success"; if (value === "measuring") return "info"; return "warning"; }
function verdictTone(value: string): "success" | "warning" | "danger" | "neutral" { if (value === "improved") return "success"; if (value === "worsened") return "danger"; if (value === "neutral") return "neutral"; return "warning"; }
