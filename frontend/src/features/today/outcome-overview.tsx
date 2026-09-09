"use client";

import Link from "next/link";
import { useState } from "react";
import type { ChangeSummary, MeasurementSummary, NextExecution, ObservedImpact, TitleFunnel } from "@/lib/api";
import { CampaignDetailDrawer } from "@/components/campaign-detail-drawer";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";

const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

export function OutcomeKpis({ changes, impact, measurement, executions }: {
  changes: ChangeSummary;
  impact: ObservedImpact;
  measurement: MeasurementSummary;
  executions: NextExecution[];
}) {
  const next = executions[0];
  const changeDetail = changeBreakdown(changes);
  return (
    <section aria-label="Resultado do SEO Agent" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Kpi
        label="Mudanças aplicadas"
        value={changes.total}
        detail={changes.total ? changeDetail : "Nenhuma alteração nos últimos 28 dias"}
        comparison={periodDelta(changes.previous_period_delta)}
      />
      <Kpi
        label="Melhoria observada"
        value={impact.improvement_rate === null ? "Sem dados" : `${decimal.format(impact.improvement_rate)}%`}
        detail={impact.measured ? `${impact.improved} de ${impact.measured} intervenções medidas melhoraram` : "Aguardando resultado pós-intervenção"}
        comparison={impact.median_ctr_delta_pp === null ? undefined : `CTR mediano ${signed(impact.median_ctr_delta_pp)} p.p.`}
      />
      <Kpi
        label="Em medição"
        value={impact.awaiting_data}
        detail={measurement.ready ? `${measurement.ready} prontas para revalidar` : measurement.waiting_google ? `${measurement.waiting_google} aguardando nova coleta Google` : "Aguardando janelas de medição"}
      />
      <Kpi
        label="Próxima execução"
        value={next ? `${next.batch_size} posts` : "Sem lote"}
        detail={next ? `${friendlyAction(next.action_type)} · ${dateTime(next.next_run_at)}` : "Nenhuma campanha ativa agendada"}
        comparison={next ? progressLabel(next) : undefined}
      />
    </section>
  );
}

export function TitleFunnelPanel({ funnel }: { funnel: TitleFunnel }) {
  const steps = [
    ["Oportunidades encontradas", funnel.opportunities],
    ["Alterações aprovadas", funnel.approved],
    ["Títulos modificados", funnel.changed],
    ["Já possuem dados suficientes", funnel.measured],
    ["Melhoraram", funnel.improved],
  ] as const;
  const rate = funnel.measured ? funnel.improved / funnel.measured * 100 : null;
  return <Card title="Funil de otimização de títulos">
    {funnel.opportunities ? <>
      <ol className="space-y-2.5" aria-label="Etapas do funil de títulos">
        {steps.map(([label, value], index) => <li key={label} className="flex items-center gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-raised)] text-[11px] font-medium text-[var(--muted)]">{index + 1}</span>
          <span className="min-w-0 flex-1 text-sm">{label}</span>
          <strong className="tabular-nums">{integer.format(value)}</strong>
        </li>)}
      </ol>
      <p className="mt-4 border-t border-[var(--border)] pt-3 text-sm"><span className="text-[var(--muted)]">Taxa de sucesso medida: </span><strong className="tabular-nums">{rate === null ? "Não medida" : `${decimal.format(rate)}%`}</strong></p>
      {!funnel.approved && <p className="mt-2 text-xs text-[var(--muted)]">Aprovações antigas sem vínculo de campanha não são inferidas.</p>}
    </> : <Empty text="Ainda não há oportunidades de título persistidas. Quando o agente registrar candidatos, o funil aparecerá aqui." />}
  </Card>;
}

export function AutomationPanel({ executions }: { executions: NextExecution[] }) {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  return <Card title="Próximas execuções">
    {executions.length ? <ul className="divide-y divide-[var(--border)]">
      {executions.map((execution) => <li key={execution.campaign_id} className="py-3 first:pt-0 last:pb-0">
        <button onClick={() => setCampaignId(execution.campaign_id)} className="block w-full rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
          <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium">{friendlyAction(execution.action_type)}</p><p className="mt-0.5 text-xs text-[var(--muted)]">{dateTime(execution.next_run_at)} · {execution.batch_size} posts no próximo lote</p></div><Badge tone="primary">Lote</Badge></div>
          <p className="mt-2 text-xs text-[var(--muted)]">{progressLabel(execution)} · {execution.url_previews.length ? execution.url_previews.map(shortUrl).join(" · ") : "Posts serão definidos pelo lote pendente"}</p>
        </button>
      </li>)}
    </ul> : <Empty text="Nenhuma campanha com itens pendentes está agendada." />}
    <div className="mt-3"><Link href="/agents"><Button size="sm" variant="secondary">Ver agenda e campanhas</Button></Link></div>
    {campaignId !== null && <CampaignDetailDrawer campaignId={campaignId} onClose={() => setCampaignId(null)} />}
  </Card>;
}

export function ObservedImpactPanel({ impact }: { impact: ObservedImpact }) {
  return <Card title="Impacto observado após a intervenção">
    {impact.measured ? <>
      <div className="flex items-end justify-between gap-3"><div><strong className="text-3xl tabular-nums">{decimal.format(impact.improvement_rate ?? 0)}%</strong><p className="text-xs text-[var(--muted)]">{impact.improved} positivas de {impact.measured} medidas</p></div><Badge tone="info">Observado, não causal</Badge></div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label="CTR mediano" value={impact.median_ctr_delta_pp === null ? "Sem dados" : `${signed(impact.median_ctr_delta_pp)} p.p.`} />
        <Metric label="Cliques por página" value={impact.median_clicks_pct === null ? "Sem dados" : `${signed(impact.median_clicks_pct)}%`} />
        <Metric label="Posição média" value={impact.median_position_gain === null ? "Sem dados" : `${signed(impact.median_position_gain)} posições`} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs"><Badge tone="success">Melhoraram {impact.improved}</Badge><Badge tone="neutral">Neutras {impact.neutral}</Badge><Badge tone="danger">Pioraram {impact.worsened}</Badge><Badge tone="info">Aguardando dados {impact.awaiting_data}</Badge></div>
      <div className="mt-4"><Link href="/improvements?view=results"><Button size="sm" variant="secondary">Ver resultados por alteração</Button></Link></div>
    </> : <Empty text="Ainda não há intervenções com uma janela pós-implementação comparável. O painel mostrará mudança observada, não causalidade atribuída ao agente." />}
  </Card>;
}

export function MeasurementPanel({ summary }: { summary: MeasurementSummary }) {
  const rows = [
    ["Prontas para revalidar", summary.ready, "success"],
    ["Aguardando 7 dias", summary.waiting_7d, "info"],
    ["Resultado principal · 28 dias", summary.waiting_28d, "neutral"],
    ["Resultado consolidado · 90 dias", summary.waiting_90d, "neutral"],
  ] as const;
  return <Card title="Em medição">
    <p className="mb-3 text-sm text-[var(--muted)]">As janelas tornam explícito quando uma mudança pode ser avaliada.</p>
    <ul className="space-y-2">{rows.map(([label, value, tone]) => <li key={label} className="flex items-center justify-between gap-3"><span className="text-sm">{label}</span><Badge tone={tone}>{value}</Badge></li>)}</ul>
    {summary.waiting_google > 0 && <p className="mt-3 text-xs text-[var(--warning)]">{summary.waiting_google} aguardando uma nova coleta do Google.</p>}
    <div className="mt-3"><Link href="/experiments"><Button size="sm" variant="secondary">Abrir experimentos</Button></Link></div>
  </Card>;
}

function Kpi({ label, value, detail, comparison }: { label: string; value: string | number; detail: string; comparison?: string }) {
  return <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4"><div className="text-2xl font-semibold tabular-nums">{value}</div><div className="mt-1 text-xs font-medium">{label}</div><div className="mt-0.5 min-h-8 text-xs text-[var(--muted)]">{detail}</div>{comparison && <div className="mt-2 text-xs font-medium text-[var(--muted)]">{comparison}</div>}</div>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"><span className="block text-xs text-[var(--muted)]">{label}</span><strong className="mt-1 block text-sm tabular-nums">{value}</strong></div>; }
function Empty({ text }: { text: string }) { return <p className="rounded-md border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted)]">{text}</p>; }
function signed(value: number) { return `${value > 0 ? "+" : ""}${decimal.format(value)}`; }
function periodDelta(value: number | null) { return value === null ? undefined : `${value >= 0 ? "+" : ""}${integer.format(value)} vs. 28 dias anteriores`; }
function dateTime(value: string | null) { if (!value) return "Aguardando agenda"; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date); }
function friendlyAction(value: string) { return (({ title_opportunity: "Otimização de títulos", title_meta: "Otimização de títulos", internal_link: "Links internos" } as Record<string, string>)[value] ?? value.replaceAll("_", " ")) || "Melhoria"; }
function progressLabel(execution: NextExecution) { const completed = execution.executed_items; const total = execution.total_items || execution.pending_items; return `${completed}/${total} concluídos · ${execution.pending_items} pendentes`; }
function changeBreakdown(changes: ChangeSummary) { const values = [[changes.titles, "títulos"], [changes.meta_descriptions, "metas"], [changes.internal_links, "links"], [changes.technical, "técnicas"]].filter(([value]) => value); return values.length ? values.map(([value, label]) => `${value} ${label}`).join(" · ") : `${changes.pages_touched} páginas tocadas`; }
function shortUrl(value: string) { return value.replace(/^https?:\/\//, "").replace(/\/$/, "").replace(/^www\./, ""); }
