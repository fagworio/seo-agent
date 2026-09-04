"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, Experiment, Revalidation } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { Pagination, pageSlice } from "@/components/pagination";

const views = [["implemented", "Implementadas"], ["waiting", "Aguardando validação"], ["results", "Resultados"], ["batches", "Lotes"]] as const;
const pageSize = 10;
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });

export default function ImprovementsPage() { return <Suspense fallback={<Loading />}><Improvements /></Suspense>; }

function Improvements() {
  const params = useSearchParams();
  const router = useRouter();
  const view = params.get("view") ?? "implemented";
  const selectedId = Number(params.get("item"));
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ["improvements"], queryFn: () => api.get<{ experiments: Experiment[] }>("/experiments?limit=200") });
  const setParam = (key: string, value: string) => { const next = new URLSearchParams(params.toString()); value ? next.set(key, value) : next.delete(key); router.replace(`/improvements?${next}`, { scroll: false }); };
  if (query.isLoading) return <Loading />;
  if (query.error) return <p className="text-sm text-[var(--danger)]">{(query.error as ApiError).message}</p>;
  const all = (query.data?.experiments ?? []).map(normalizeExperiment);
  const items = view === "waiting" ? all.filter((item) => item.measurement_state !== "measured") : view === "results" ? all.filter((item) => item.measurement_state === "measured") : view === "batches" ? [] : all;
  const selected = all.find((item) => item.id === selectedId);
  const measured = all.filter((item) => item.measurement_state === "measured");

  return <div className="space-y-5"><header><h1 className="text-xl font-semibold">Melhorias</h1><p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">Acompanhe o que foi implementado, quando será revalidado e qual resultado foi realmente observado.</p></header>
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-5" aria-label="Resumo das melhorias"><Summary label="Implementadas" value={all.length} /><Summary label="Aguardando dados" value={all.length - measured.length} /><Summary label="Melhoraram" value={all.filter((item) => item.verdict === "improved").length} /><Summary label="Neutras" value={all.filter((item) => item.verdict === "neutral").length} /><Summary label="Regressões" value={all.filter((item) => item.verdict === "worsened").length} /></section>
    <nav aria-label="Visões de melhorias" className="flex flex-wrap gap-2">{views.map(([key, label]) => <Button key={key} size="sm" variant={view === key ? "primary" : "ghost"} onClick={() => { setPage(1); setParam("view", key); }}>{label}</Button>)}</nav>
    {view === "batches" ? <EmptyBatches /> : <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]"><table className="w-full text-sm"><thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]"><tr><th className="px-3 py-2">Status</th><th className="px-3 py-2">Melhoria</th><th className="px-3 py-2">Página</th><th className="px-3 py-2">Previsto</th><th className="px-3 py-2">Resultado observado</th></tr></thead><tbody>{pageSlice(items, page, pageSize).map((item) => <tr key={item.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]"><td className="px-3 py-3"><StatusBadge item={item} /></td><td className="max-w-xs px-3 py-3"><button className="text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]" onClick={() => setParam("item", String(item.id))}>{friendlyType(item.opportunity_type)}</button><span className="block text-xs text-[var(--muted)]">{item.implemented_action || "Ação não descrita"}</span></td><td className="max-w-xs truncate px-3 py-3 text-xs">{item.keyword || item.url}</td><td className="px-3 py-3 tabular-nums">{forecastLabel(item.forecast)}</td><td className="px-3 py-3 tabular-nums">{resultLabel(item)}</td></tr>)}{!items.length && <tr><td colSpan={5} className="px-3 py-8 text-center text-[var(--muted)]">Nenhuma melhoria nesta visão.</td></tr>}</tbody></table><Pagination page={page} pageSize={pageSize} total={items.length} onPageChange={setPage} label="melhorias" /></div>}
    {selected && <ImprovementDrawer item={selected} close={() => setParam("item", "")} />}
  </div>;
}

function ImprovementDrawer({ item, close }: { item: Experiment; close: () => void }) {
  const before = group(item.baseline, "gsc"); const after = group(item.current, "gsc"); const delta = group(item.delta, "gsc"); const revalidation = item.revalidation;
  return <Drawer title="Detalhes da melhoria" onClose={close}><div className="flex justify-between gap-3"><div><StatusBadge item={item} /><h2 className="mt-2 text-lg font-semibold">{item.keyword || friendlyType(item.opportunity_type)}</h2><p className="mt-1 text-sm text-[var(--muted)]">{item.implemented_action}</p></div><Button size="sm" variant="ghost" onClick={close}>Fechar</Button></div>
    <section className="mt-5"><h3 className="font-semibold">Implementação</h3><dl className="mt-2 space-y-1 text-sm"><Row label="Data" value={dateLabel(item.implemented_at)} /><Row label="Página" value={item.url || "Não informada"} /><Row label="Tipo" value={friendlyType(item.opportunity_type)} /></dl></section>
    <MetricSection title="Antes — baseline Google" values={before} />
    <section className="mt-5"><h3 className="font-semibold">Previsão</h3>{Object.keys(item.forecast).length ? <div className="mt-2 grid grid-cols-2 gap-2"><Metric label="CTR esperado" value={formatPercent(item.forecast.expected_ctr)} /><Metric label="Oportunidade de cliques" value={formatNumber(item.forecast.gap_clicks)} /><Metric label="Conservador" value={formatNumber(item.forecast.conservative_clicks)} /><Metric label="Cenário realista" value={formatNumber(item.forecast.realistic_clicks)} /></div> : <Missing text="Nenhuma projeção foi registrada para esta melhoria." />}<p className="mt-2 text-xs text-[var(--muted)]">Previsão é cenário, não resultado garantido.</p></section>
    <MetricSection title={`Resultado observado${item.latest_result_window ? ` — ${item.latest_result_window}` : ""}`} values={after} delta={delta} />
    <section className="mt-5"><h3 className="font-semibold">Revalidação</h3><div className="mt-2 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm"><Row label="Estado" value={revalidationLabel(revalidation.state)} /><Row label="Revisar a partir de" value={dateLabel(revalidation.due_at)} /><Row label="Baseline" value={revalidation.baseline_status === "available" ? "Disponível" : "Ausente"} /><Row label="Última janela Google" value={dateLabel(revalidation.latest_google_window_end)} /></div><p className="mt-2 text-xs text-[var(--muted)]">A revalidação automática só grava resultado quando existe baseline e uma resposta válida do Google.</p></section>
    <div className="mt-5 flex gap-2"><Link href="/experiments"><Button variant="secondary">Ver experimentos</Button></Link><Link href={`/pages/${encodeURIComponent(item.url)}`}><Button variant="secondary">Ver histórico da página</Button></Link></div>
  </Drawer>;
}

function MetricSection({ title, values, delta }: { title: string; values: Record<string, unknown>; delta?: Record<string, unknown> }) { return <section className="mt-5"><h3 className="font-semibold">{title}</h3>{Object.keys(values).length ? <div className="mt-2 grid grid-cols-2 gap-2"><Metric label="CTR" value={formatPercent(values.ctr)} note={deltaLabel(delta, "ctr")} /><Metric label="Cliques" value={formatNumber(values.clicks)} note={deltaLabel(delta, "clicks")} /><Metric label="Impressões" value={formatNumber(values.impressions)} note={deltaLabel(delta, "impressions")} /><Metric label="Posição" value={formatDecimal(values.position)} note={deltaLabel(delta, "position")} /></div> : <Missing text="Ainda não existem dados comparáveis para esta etapa." />}</section>; }
function Metric({ label, value, note }: { label: string; value: string; note?: string }) { return <div className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"><span className="text-xs text-[var(--muted)]">{label}</span><strong className="mt-1 block tabular-nums">{value}</strong>{note && <span className="text-xs text-[var(--muted)]">{note}</span>}</div>; }
function Summary({ label, value }: { label: string; value: number }) { return <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4"><strong className="text-2xl tabular-nums">{value}</strong><span className="mt-1 block text-xs text-[var(--muted)]">{label}</span></div>; }
function StatusBadge({ item }: { item: Experiment }) { const status = improvementStatus(item); return <Badge tone={status.tone}>{status.label}</Badge>; }
function EmptyBatches() { return <div className="rounded-[9px] border border-dashed border-[var(--border)] p-8 text-center"><h2 className="font-semibold">Nenhum lote registrado</h2><p className="mx-auto mt-2 max-w-xl text-sm text-[var(--muted)]">A execução em lote exige persistência de lote, preview consolidado e rollback por item. A interface não simula essa funcionalidade enquanto o backend não registrar essas garantias.</p></div>; }
function Missing({ text }: { text: string }) { return <p className="mt-2 rounded-md border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted)]">{text}</p>; }
function Row({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">{label}</dt><dd className="max-w-[65%] break-words text-right">{value || "—"}</dd></div>; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function group(parent: Record<string, unknown> | undefined, key: string) { return record(parent?.[key]); }
function numeric(value: unknown) { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function formatNumber(value: unknown) { const parsed = numeric(value); return parsed === null ? "—" : integer.format(parsed); }
function formatDecimal(value: unknown) { const parsed = numeric(value); return parsed === null ? "—" : decimal.format(parsed); }
function formatPercent(value: unknown) { const parsed = numeric(value); return parsed === null ? "—" : percent.format(parsed); }
function deltaLabel(delta: Record<string, unknown> | undefined, key: string) { const parsed = numeric(delta?.[`${key}_delta`] ?? delta?.[key]); return parsed === null ? "" : `${parsed > 0 ? "+" : ""}${decimal.format(parsed)} observado`; }
function forecastLabel(value?: Record<string, unknown>) { const realistic = numeric(value?.realistic_clicks); return realistic === null ? "Sem previsão" : `${realistic >= 0 ? "+" : ""}${integer.format(realistic)} cliques`; }
function resultLabel(item: Experiment) { const clicks = numeric(group(item.delta, "gsc").clicks_delta); return clicks === null ? "Aguardando medição" : `${clicks >= 0 ? "+" : ""}${integer.format(clicks)} cliques`; }
function friendlyType(value?: string) { return (({ title_meta: "Título e meta description", expand_existing: "Conteúdo expandido", internal_link: "Link interno", refresh: "Atualização de conteúdo" } as Record<string, string>)[value ?? ""] ?? value?.replaceAll("_", " ")) || "Melhoria"; }
function improvementStatus(item: Experiment): { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" } { if (item.verdict === "improved") return { label: "Melhorou", tone: "success" }; if (item.verdict === "worsened") return { label: "Piorou", tone: "danger" }; if (item.verdict === "neutral" || item.verdict === "mixed") return { label: "Neutro/misto", tone: "neutral" }; const state = item.revalidation?.state; if (state === "ready") return { label: "Pronta para revalidar", tone: "warning" }; if (state === "waiting_google") return { label: "Aguardando Google", tone: "warning" }; if (state === "waiting_7d") return { label: "Aguardando 7 dias", tone: "info" }; return { label: "Implementada", tone: "neutral" }; }
function revalidationLabel(value?: string) { return ({ ready: "Pronta para revalidar", waiting_google: "Aguardando nova coleta Google", waiting_7d: "Aguardando 7 dias", measured: "Medida" } as Record<string, string>)[value ?? ""] ?? "Não agendada"; }
function dateLabel(value?: string) { if (!value) return "—"; const date = new Date(value.length === 10 ? `${value}T12:00:00` : value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("pt-BR").format(date); }
function normalizeExperiment(value: Experiment, index: number): Experiment {
  const raw = value as Partial<Experiment>;
  return {
    id: raw.id ?? -(index + 1),
    keyword: raw.keyword ?? "",
    opportunity_type: raw.opportunity_type ?? "",
    url: raw.url ?? "",
    implemented_action: raw.implemented_action ?? "",
    implemented_at: raw.implemented_at ?? "",
    baseline: record(raw.baseline),
    current: record(raw.current),
    delta: record(raw.delta),
    forecast: record(raw.forecast),
    latest_result_window: raw.latest_result_window ?? "",
    revalidation: record(raw.revalidation) as Partial<Revalidation>,
    verdict: raw.verdict ?? null,
    windows: record(raw.windows) as Record<string, boolean>,
    measurement_state: raw.measurement_state ?? "waiting_data",
  };
}
function Loading() { return <p className="text-sm text-[var(--muted)]">Carregando melhorias…</p>; }
