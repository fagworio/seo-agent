import Link from "next/link";
import type { GoogleDataSummary, ImprovementSummary, Revalidation, SearchQuerySummary, SearchTrendPoint } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";

const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });

export function GoogleTrust({ data }: { data: GoogleDataSummary }) {
  const hasStoredData = data.data_status === "available";
  return <Card title="Confiabilidade dos dados Google">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><Badge tone={hasStoredData ? "success" : "warning"}>{hasStoredData ? "Dados GSC disponíveis" : "Dados GSC ausentes"}</Badge><p className="mt-2 text-sm text-[var(--muted)]">{hasStoredData ? `Janela armazenada: ${data.gsc_window_start} a ${data.gsc_window_end}` : "Não há janela armazenada para sustentar análises de busca."}</p></div><Badge tone={data.connection_configured ? "success" : "warning"}>{data.connection_configured ? "Conexão configurada" : "Conexão não configurada"}</Badge></div>
    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4"><SmallMetric label="Linhas GSC" value={integer.format(data.gsc_rows)} /><SmallMetric label="Linhas GA4" value={integer.format(data.ga4_rows)} /><SmallMetric label="Com evidência Google" value={integer.format(data.opportunities_with_google)} /><SmallMetric label="Sem evidência Google" value={integer.format(data.opportunities_without_google)} /></div>
    {!data.connection_configured && hasStoredData && <p className="mt-3 text-xs text-[var(--warning)]">Os dados armazenados continuam válidos para a janela indicada, mas uma nova coleta exige restabelecer a conexão Google.</p>}
  </Card>;
}

export function OrganicTrend({ points }: { points: SearchTrendPoint[] }) {
  if (!points.length) return <Card title="Desempenho orgânico"><Empty text="Nenhuma janela GSC armazenada. O sistema não pode calcular tendência." /></Card>;
  const maximum = Math.max(...points.map((point) => point.impressions), 1);
  const latest = points[points.length - 1];
  return <Card title="Desempenho orgânico — Search Console">
    <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4"><SmallMetric label="Impressões" value={integer.format(latest.impressions)} /><SmallMetric label="Cliques" value={integer.format(latest.clicks)} /><SmallMetric label="CTR" value={latest.ctr === null ? "—" : percent.format(latest.ctr)} /><SmallMetric label="Posição média" value={latest.position === null ? "—" : decimal.format(latest.position)} /></div>
    <div className="flex h-40 items-end gap-3 border-b border-[var(--border)] px-2" role="img" aria-label="Impressões por janela do Search Console">{points.map((point) => <div key={point.window_start} className="flex min-w-12 flex-1 flex-col items-center justify-end gap-1"><span className="text-xs tabular-nums text-[var(--muted)]">{integer.format(point.impressions)}</span><div className="w-full max-w-16 rounded-t bg-[var(--primary)]" style={{ height: `${Math.max(8, (point.impressions / maximum) * 104)}px` }} /><span className="pb-2 text-[10px] text-[var(--muted)]">{shortDate(point.window_start)}</span></div>)}</div>
    <p className="mt-3 text-xs text-[var(--muted)]">{points.length === 1 ? "Somente uma janela está disponível; ainda não há base para afirmar tendência." : `${points.length} janelas reais armazenadas. Não há interpolação de períodos ausentes.`}</p>
  </Card>;
}

export function TopSearches({ searches }: { searches: SearchQuerySummary[] }) {
  return <Card title="Buscas que trouxeram visibilidade">{searches.length ? <><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-xs text-[var(--muted)]"><tr><th className="pb-2">Busca realizada</th><th className="pb-2">Impressões</th><th className="pb-2">Cliques</th><th className="pb-2">CTR</th><th className="pb-2">Posição</th></tr></thead><tbody>{searches.map((search) => <tr key={search.query} className="border-t border-[var(--border)]"><td className="max-w-64 py-2 pr-3 font-medium">{search.query}</td><td className="py-2 tabular-nums">{integer.format(search.impressions)}</td><td className="py-2 tabular-nums">{integer.format(search.clicks)}</td><td className="py-2 tabular-nums">{search.ctr === null ? "—" : percent.format(search.ctr)}</td><td className="py-2 tabular-nums">{search.position === null ? "—" : decimal.format(search.position)}</td></tr>)}</tbody></table></div><p className="mt-3 text-xs text-[var(--muted)]">Fonte: Google Search Console · janela {searches[0].window_start} a {searches[0].window_end}.</p></> : <Empty text="Nenhuma consulta do Search Console disponível." />}</Card>;
}

export function ImprovementChart({ summary }: { summary: ImprovementSummary }) {
  const values = [["Melhora observada", summary.improved, "bg-[var(--success)]"], ["Sem mudança relevante", summary.neutral, "bg-[var(--info)]"], ["Piora observada", summary.worsened, "bg-[var(--danger)]"], ["Dados insuficientes", summary.insufficient_data, "bg-[var(--warning)]"]] as const;
  const maximum = Math.max(...values.map((value) => value[1]), 1);
  return <Card title="Resultado das melhorias"><div className="flex items-center justify-between gap-3"><div><strong className="text-2xl tabular-nums">{summary.measured}</strong><p className="text-xs text-[var(--muted)]">intervenções medidas</p></div><div className="text-right"><strong className="text-2xl tabular-nums">{summary.implemented}</strong><p className="text-xs text-[var(--muted)]">implementadas</p></div></div>{summary.measured ? <div className="mt-4 space-y-3">{values.map(([label, value, color]) => <div key={label}><div className="mb-1 flex justify-between text-xs"><span>{label}</span><span className="tabular-nums">{value}</span></div><div className="h-2 rounded-full bg-[var(--surface-raised)]"><div className={`h-2 rounded-full ${color}`} style={{ width: `${(value / maximum) * 100}%` }} /></div></div>)}</div> : <Empty text="Nenhuma melhoria possui uma janela pós-implementação medida. O painel não atribui ganho antes da revalidação." />}</Card>;
}

export function RevalidationPanel({ items, summary }: { items: Revalidation[]; summary: ImprovementSummary }) {
  return <Card title="Revalidações após a implementação"><div className="mb-3 flex flex-wrap gap-2"><Badge tone={summary.ready ? "warning" : "neutral"}>{summary.ready} prontas</Badge><Badge tone={summary.waiting_7d ? "info" : "neutral"}>{summary.waiting_7d} aguardando 7 dias</Badge><Badge tone={summary.waiting_google ? "warning" : "neutral"}>{summary.waiting_google} aguardando Google</Badge></div>{items.length ? <ul className="divide-y divide-[var(--border)]">{items.map((item) => <li key={item.id} className="py-3 first:pt-0"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate font-medium">{item.keyword || item.implemented_action || item.url}</p><p className="mt-0.5 truncate text-xs text-[var(--muted)]">{item.implemented_action || item.url}</p></div><Badge tone={revalidationTone(item.state)}>{revalidationLabel(item.state)}</Badge></div><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted)]"><span>Implementada: {dateLabel(item.implemented_at)}</span><span>Revisar a partir de: {dateLabel(item.due_at)}</span><span>Baseline: {item.baseline_status === "available" ? "disponível" : "ausente"}</span>{item.latest_google_window_end && <span>Último Google: {dateLabel(item.latest_google_window_end)}</span>}</div></li>)}</ul> : <Empty text="Nenhuma intervenção implementada está aguardando revalidação." />}<div className="mt-3"><Link href="/experiments"><Button size="sm" variant="secondary">Abrir experimentos</Button></Link></div></Card>;
}

function SmallMetric({ label, value }: { label: string; value: string }) { return <div className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"><span className="block text-xs text-[var(--muted)]">{label}</span><strong className="mt-1 block tabular-nums">{value}</strong></div>; }
function Empty({ text }: { text: string }) { return <p className="mt-3 rounded-md border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted)]">{text}</p>; }
function shortDate(value: string) { const [year, month, day] = value.split("-"); return year && month && day ? `${day}/${month}` : value; }
function dateLabel(value: string) { if (!value) return "—"; const date = new Date(value.length === 10 ? `${value}T12:00:00` : value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("pt-BR").format(date); }
function revalidationLabel(value: string) { return ({ waiting_7d: "Aguardando 7 dias", waiting_google: "Aguardando nova coleta", ready: "Pronta para revalidar", measured: "Medida" } as Record<string, string>)[value] ?? value; }
function revalidationTone(value: string): "success" | "warning" | "info" | "neutral" { if (value === "measured") return "success"; if (value === "ready" || value === "waiting_google") return "warning"; if (value === "waiting_7d") return "info"; return "neutral"; }
