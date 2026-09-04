"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, TodayResponse, ApiError, GoogleDataSummary, ImprovementSummary } from "@/lib/api";
import { presentOpportunity } from "@/lib/opportunity-presentation";
import { opportunityEvidenceSummary } from "@/features/opportunities/decision-insight";
import { GoogleTrust, ImprovementChart, OrganicTrend, RevalidationPanel, TopSearches } from "@/features/today/dashboard-insights";
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
  const revalidationAttention = improvementSummary.ready + improvementSummary.waiting_google;
  return <div className="space-y-6">
    <header><h1 className="text-xl font-semibold">Hoje</h1><p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">O que precisa de decisão, quais dados sustentam as análises e quando medir as melhorias implementadas.</p></header>

    <section aria-label="Resumo de atenção" className="grid grid-cols-2 gap-4 lg:grid-cols-4"><Kpi label="Decisões pendentes" value={today.needs_attention} detail="Caixa de trabalho" /><Kpi label="Revalidações exigindo dados" value={revalidationAttention} detail="Prazo atingido ou coleta pendente" /><Kpi label="Melhoras observadas" value={improvementSummary.improved} detail={`${improvementSummary.measured} intervenções medidas`} /><Kpi label="Cobertura Google" value={`${googleData.opportunities_with_google}/${googleData.opportunities_total}`} detail="oportunidades com evidência GSC" /></section>

    <GoogleTrust data={googleData} />

    <div className="grid gap-6 xl:grid-cols-2"><RecentRuns runs={today.recent_runs} /><RevalidationPanel items={today.revalidations} summary={improvementSummary} /></div>

    <div className="grid gap-6 xl:grid-cols-2"><OrganicTrend points={today.search_trend} /><ImprovementChart summary={improvementSummary} /></div>

    <TopSearches searches={today.top_searches} />

    <div className="grid gap-6 xl:grid-cols-2"><TopOpportunities opportunities={today.top_opportunities} /><SourceWarnings warnings={today.integration_warnings} /></div>
  </div>;
}

function RecentRuns({ runs }: { runs: TodayResponse["today"]["recent_runs"] }) {
  return <Card title="Execuções recentes">{runs.length ? <ul className="divide-y divide-[var(--border)]">{runs.map((run) => <li key={run.id} className="py-2 first:pt-0"><Link href={`/agents/runs/${run.id}`} className="flex items-center justify-between gap-3 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"><div><p className="font-medium">{run.agent}</p><p className="text-xs text-[var(--muted)]">{run.intent || "Análise operacional"} · {run.urls_analyzed} URLs</p></div><Badge tone={runTone(run.status)}>{runLabel(run.status)}</Badge></Link></li>)}</ul> : <p className="text-sm text-[var(--muted)]">Nenhuma execução foi registrada. Métricas existentes podem ter sido coletadas por comandos anteriores sem rastreamento de run.</p>}<div className="mt-3"><Link href="/agents"><Button size="sm" variant="secondary">Ver agentes e execuções</Button></Link></div></Card>;
}

function TopOpportunities({ opportunities }: { opportunities: TodayResponse["today"]["top_opportunities"] }) {
  return <Card title="Decisões sustentadas por dados Google">{opportunities.length ? <ul className="divide-y divide-[var(--border)]">{opportunities.map((opportunity) => { const presentation = presentOpportunity(opportunity); return <li key={opportunity.id} className="py-3 first:pt-0 last:pb-0"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium">{presentation.label}</p><p className="mt-0.5 truncate text-sm">{opportunity.title || opportunity.url}</p></div><span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">{opportunityEvidenceSummary(opportunity)}</span></div><p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">{presentation.detail}</p><Link className="mt-2 inline-flex" href={`/work?source=${encodeURIComponent(opportunity.source)}&item=${encodeURIComponent(opportunity.id)}`}><Button size="sm" variant="secondary">{presentation.action}</Button></Link></li>; })}</ul> : <p className="text-sm text-[var(--muted)]">Nenhuma decisão pendente possui evidência GSC para a janela atual. Itens sem Google permanecem visíveis na Caixa de trabalho como dados parciais.</p>}</Card>;
}

function SourceWarnings({ warnings }: { warnings: TodayResponse["today"]["integration_warnings"] }) {
  return <Card title="Fontes que precisam de atenção"><ul className="space-y-2">{warnings.map((source) => <li key={source.source} className="flex items-start justify-between gap-3 text-sm"><div><p className="font-medium">{source.source}</p><p className="text-xs text-[var(--muted)]">{source.limitations || source.detail || "Fonte parcial ou indisponível."}</p></div><Badge tone="warning">{source.data_status}</Badge></li>)}{!warnings.length && <li className="text-sm text-[var(--muted)]">Todas as fontes configuradas estão disponíveis.</li>}</ul><div className="mt-3"><Link href="/integrations"><Button size="sm" variant="secondary">Ver fontes de dados</Button></Link></div></Card>;
}

function Kpi({ label, value, detail }: { label: string; value: number | string; detail: string }) { return <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4"><div className="text-2xl font-semibold tabular-nums">{value}</div><div className="mt-1 text-xs font-medium">{label}</div><div className="mt-0.5 text-xs text-[var(--muted)]">{detail}</div></div>; }
function runLabel(status: string) { return ({ success: "Concluída", failed: "Falhou", partial: "Parcial", running: "Em execução" } as Record<string, string>)[status] ?? status; }
function runTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" { if (status === "success") return "success"; if (status === "failed") return "danger"; if (status === "partial") return "warning"; if (status === "running") return "info"; return "neutral"; }
