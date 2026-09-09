"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, TodayResponse, ApiError, ChangeSummary, GoogleDataSummary, ImprovementSummary, MeasurementSummary, NextExecution, ObservedImpact, TitleFunnel } from "@/lib/api";
import { presentOpportunity } from "@/lib/opportunity-presentation";
import { opportunityEvidenceSummary } from "@/features/opportunities/decision-insight";
import { GoogleTrust, GoogleSignalsPanel, OrganicTrend, TopSearches } from "@/features/today/dashboard-insights";
import { AutomationPanel, MeasurementPanel, ObservedImpactPanel, OutcomeKpis, TitleFunnelPanel } from "@/features/today/outcome-overview";
import { TitleImpactWidget } from "@/features/today/title-impact-widget";
import { DashboardWidgetLayout, type DashboardWidget } from "@/features/today/widget-layout";
import { Card } from "@/design-system/card";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";

export default function TodayPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["today"], queryFn: () => api.get<TodayResponse>("/dashboard/today?limit=8") });
  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando dados operacionais…</div>;
  if (error) {
    const apiError = error as ApiError;
    return apiError.status === 401 ? <Card className="mx-auto max-w-md text-center"><div className="mb-2 text-sm font-semibold">Não autenticado</div><p className="mb-4 text-sm text-[var(--muted)]">Entre para ver o painel de operações.</p><Link href="/login"><Button>Ir para o login</Button></Link></Card> : <div className="text-sm text-[var(--danger)]">{apiError.message}</div>;
  }
  // API and frontend may be restarted independently in local installations.
  // Normalize the previous dashboard contract instead of crashing while an old
  // API process or cached response is still in use.
  const rawToday = data!.today as Partial<TodayResponse["today"]>;
  const improvementSummary: ImprovementSummary = {
    implemented: 0, measured: 0, improved: 0, neutral: 0, worsened: 0,
    insufficient_data: 0, waiting_7d: 0, waiting_google: 0, ready: 0,
    ...rawToday.improvement_summary,
  };
  const googleData: GoogleDataSummary = {
    data_status: "missing", connection_configured: false,
    gsc_window_start: "", gsc_window_end: "", gsc_rows: 0,
    ga4_rows: 0, ga4_window_end: "", ga4_collected_at: "",
    opportunities_total: rawToday.top_opportunities?.length ?? 0,
    opportunities_with_google: 0,
    opportunities_without_google: rawToday.top_opportunities?.length ?? 0,
    ...rawToday.google_data,
  };
  const changeSummary: ChangeSummary = {
    total: 0, pages_touched: 0, titles: 0, meta_descriptions: 0,
    internal_links: 0, technical: 0, previous_period_delta: null,
    ...rawToday.change_summary,
  };
  const titleFunnel: TitleFunnel = {
    opportunities: 0, approved: 0, changed: 0, measured: 0, improved: 0,
    ...rawToday.title_funnel,
  };
  const observedImpact: ObservedImpact = {
    measured: 0, improved: 0, neutral: 0, worsened: 0, awaiting_data: 0,
    improvement_rate: null, median_ctr_delta_pp: null, median_clicks_pct: null,
    median_position_gain: null, ...rawToday.observed_impact,
  };
  const measurementSummary: MeasurementSummary = {
    ready: 0, waiting_7d: 0, waiting_28d: 0, waiting_90d: 0, waiting_google: 0,
    ...rawToday.measurement_summary,
  };
  const nextExecutions: NextExecution[] = rawToday.next_executions ?? [];
  const today = {
    ...rawToday,
    needs_attention: rawToday.needs_attention ?? 0,
    recent_runs: rawToday.recent_runs ?? [],
    // Legacy opportunities were not guaranteed to have GSC evidence.
    top_opportunities: rawToday.google_data ? (rawToday.top_opportunities ?? []) : [],
    integration_warnings: rawToday.integration_warnings ?? [],
    google_data: googleData,
    search_trend: rawToday.search_trend ?? [],
    top_searches: rawToday.top_searches ?? [],
    revalidations: rawToday.revalidations ?? [],
    improvement_summary: improvementSummary,
  };
  const widgets: DashboardWidget[] = [
    { id: "title-impact", label: "Impacto acumulado dos títulos", className: "xl:col-span-2", content: <TitleImpactWidget /> },
    { id: "outcome-summary", label: "Resumo de resultados", className: "xl:col-span-2", content: <OutcomeKpis changes={changeSummary} impact={observedImpact} measurement={measurementSummary} executions={nextExecutions} /> },
    { id: "google-trust", label: "Saúde dos dados Google", className: "xl:col-span-2", content: <GoogleTrust data={googleData} /> },
    { id: "title-funnel", label: "Funil de otimização de títulos", content: <TitleFunnelPanel funnel={titleFunnel} /> },
    { id: "automation", label: "Próximas execuções", content: <AutomationPanel executions={nextExecutions} /> },
    { id: "observed-impact", label: "Impacto observado", content: <ObservedImpactPanel impact={observedImpact} /> },
    { id: "measurement", label: "Em medição", content: <MeasurementPanel summary={measurementSummary} /> },
    { id: "recent-activity", label: "Atividade recente", content: <RecentRuns runs={today.recent_runs} /> },
    { id: "opportunities", label: "Decisões sustentadas por Google", content: <TopOpportunities opportunities={today.top_opportunities} /> },
    { id: "organic-trend", label: "Desempenho orgânico", content: <OrganicTrend points={today.search_trend} /> },
    { id: "source-warnings", label: "Fontes que precisam de atenção", content: <SourceWarnings warnings={today.integration_warnings} /> },
    { id: "top-searches", label: "Buscas com visibilidade", className: "xl:col-span-2", content: <TopSearches searches={today.top_searches} /> },
    { id: "google-signals", label: "Sinais Google", className: "xl:col-span-2", content: <GoogleSignalsPanel signals={rawToday.google_signals ?? {}} /> },
    { id: "topic-movers", label: "Tópicos em movimento", className: "xl:col-span-2", content: <TopicMovers today={today} /> },
  ];
  return <div className="space-y-6">
    <header><h1 className="text-xl font-semibold">Hoje</h1><p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">O que o SEO Agent mudou, o que está sendo medido e qual lote será executado em seguida.</p></header>
    <DashboardWidgetLayout widgets={widgets} />
  </div>;
}

function RecentRuns({ runs }: { runs: TodayResponse["today"]["recent_runs"] }) {
  return <Card title="Atividade recente do SEO Agent">{runs.length ? <ul className="divide-y divide-[var(--border)]">{runs.map((run) => <li key={run.id} className="py-2 first:pt-0"><Link href={`/agents/runs/${run.id}`} className="flex items-center justify-between gap-3 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"><div><p className="font-medium">{run.agent}</p><p className="text-xs text-[var(--muted)]">{run.intent || "Análise operacional"} · {run.urls_analyzed} URLs · {run.executed_changes_count} mudanças executadas</p></div><Badge tone={runTone(run.status)}>{runLabel(run.status)}</Badge></Link></li>)}</ul> : <p className="text-sm text-[var(--muted)]">Nenhuma execução foi registrada. Métricas existentes podem ter sido coletadas por comandos anteriores sem rastreamento de run.</p>}<div className="mt-3"><Link href="/agents"><Button size="sm" variant="secondary">Ver agentes e execuções</Button></Link></div></Card>;
}

function TopOpportunities({ opportunities }: { opportunities: TodayResponse["today"]["top_opportunities"] }) {
  return <Card title="Decisões sustentadas por dados Google">{opportunities.length ? <ul className="divide-y divide-[var(--border)]">{opportunities.map((opportunity) => { const presentation = presentOpportunity(opportunity); return <li key={opportunity.id} className="py-3 first:pt-0 last:pb-0"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium">{presentation.label}</p><p className="mt-0.5 truncate text-sm">{opportunity.title || opportunity.url}</p></div><span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">{opportunityEvidenceSummary(opportunity)}</span></div><p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">{presentation.detail}</p>{opportunity.rankability_v2?.opportunity?.score != null && <p className="mt-1 text-xs tabular-nums">Oportunidade {Math.round(opportunity.rankability_v2.opportunity.score)} · Rank {Math.round(opportunity.rankability_v2.query_rankability?.score ?? 0)} · Headroom {Math.round(opportunity.rankability_v2.headroom?.score ?? 0)} · Conf {opportunity.rankability_v2.confidence?.label ?? "—"}</p>}<Link className="mt-2 inline-flex" href={`/work?source=${encodeURIComponent(opportunity.source)}&item=${encodeURIComponent(opportunity.id)}`}><Button size="sm" variant="secondary">{presentation.action}</Button></Link></li>; })}</ul> : <p className="text-sm text-[var(--muted)]">Nenhuma decisão pendente possui evidência GSC para a janela atual. Itens sem Google permanecem visíveis na Caixa de trabalho como dados parciais.</p>}</Card>;
}

function SourceWarnings({ warnings }: { warnings: TodayResponse["today"]["integration_warnings"] }) {
  return <Card title="Fontes que precisam de atenção"><ul className="space-y-2">{warnings.map((source) => <li key={source.source} className="flex items-start justify-between gap-3 text-sm"><div><p className="font-medium">{source.source}</p><p className="text-xs text-[var(--muted)]">{source.limitations || source.detail || "Fonte parcial ou indisponível."}</p></div><Badge tone="warning">{source.data_status}</Badge></li>)}{!warnings.length && <li className="text-sm text-[var(--muted)]">Todas as fontes configuradas estão disponíveis.</li>}</ul><div className="mt-3"><Link href="/integrations"><Button size="sm" variant="secondary">Ver fontes de dados</Button></Link></div></Card>;
}

function runLabel(status: string) { return ({ success: "Concluída", failed: "Falhou", partial: "Parcial", running: "Em execução" } as Record<string, string>)[status] ?? status; }
function runTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" { if (status === "success") return "success"; if (status === "failed") return "danger"; if (status === "partial") return "warning"; if (status === "running") return "info"; return "neutral"; }

function TopicMovers({ today }: { today: { emerging_topics?: { topic: string; authority: number; momentum: number | null }[]; declining_topics?: { topic: string; authority: number; momentum: number | null }[] } }) {
  const emerging = today.emerging_topics ?? [];
  const declining = today.declining_topics ?? [];
  if (!emerging.length && !declining.length) return null;
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {emerging.length > 0 && <Card title="Tópicos ganhando força"><ul className="space-y-2">{emerging.map((t) => <li key={t.topic} className="flex items-center justify-between text-sm"><span className="font-medium">{t.topic}</span><Badge tone="success">↑ {Math.round(t.momentum ?? 0)}%</Badge></li>)}</ul></Card>}
      {declining.length > 0 && <Card title="Perdendo visibilidade"><ul className="space-y-2">{declining.map((t) => <li key={t.topic} className="flex items-center justify-between text-sm"><span className="font-medium">{t.topic}</span><Badge tone="danger">↓ {Math.abs(Math.round(t.momentum ?? 0))}%</Badge></li>)}</ul></Card>}
    </div>
  );
}
