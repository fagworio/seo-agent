"use client";

import { Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, Opportunity } from "@/lib/api";
import { presentOpportunity } from "@/lib/opportunity-presentation";
import { opportunityEvidenceSummary, DecisionInsight } from "@/features/opportunities/decision-insight";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { Pagination, pageSlice } from "@/components/pagination";
import { DelegateCampaignModal } from "@/components/delegate-campaign-modal";

const filters = [["", "Todas"], ["checklist", "Melhorias SEO"], ["content_brief", "Planos de conteúdo"], ["backlog", "Editorial"], ["interlink", "Links internos"]] as const;
const pageSize = 10;
type Decision = "approve" | "reject" | "snooze";

export default function WorkPage() {
  return <Suspense fallback={<Loading />}><Workbox /></Suspense>;
}

function Workbox() {
  const router = useRouter();
  const params = useSearchParams();
  const source = params.get("source") ?? "";
  const selectedId = params.get("item");
  const [page, setPage] = useState(Math.max(1, Number(params.get("page") ?? "1") || 1));
  const [bulk, setBulk] = useState<Set<string>>(new Set());
  const [delegateFps, setDelegateFps] = useState<string[] | null>(null);
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const query = useQuery({ queryKey: ["work-items", source], queryFn: () => api.get<{ work_items: Opportunity[] }>(`/work-items?limit=200${source ? `&source=${source}` : ""}`) });

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    value ? next.set(key, value) : next.delete(key);
    router.replace(`/work?${next}`, { scroll: false });
  };

  useEffect(() => setPage(1), [source]);

  const decision = useMutation({
    mutationFn: ({ id, action }: { id: string; action: Decision }) => api.post(`/work-items/${id}/${action}`, {}, me.data?.csrf_token),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["work-items"] }); setParam("item", ""); },
  });
  const resolve = useMutation({
    mutationFn: (urls: string[]) => api.post<{ fingerprints: string[] }>("/campaigns/resolve", { urls }, me.data?.csrf_token),
    onSuccess: (res) => setDelegateFps(res.fingerprints),
  });

  if (query.isLoading) return <Loading />;
  if (query.error) return <p className="text-sm text-[var(--danger)]">{(query.error as ApiError).message}</p>;
  const items = query.data?.work_items ?? [];
  const selected = items.find((item) => item.id === selectedId);
  const visible = pageSlice(items, page, pageSize);
  const canReview = me.data?.user.permissions.includes("opportunity.review") ?? false;
  const selectedUrls = items.filter((i) => bulk.has(i.id) && i.url).map((i) => i.url);
  const toggleBulk = (id: string) => setBulk((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-xl font-semibold">Caixa de trabalho</h1><p className="mt-1 text-sm text-[var(--muted)]">Compare evidência, potencial, risco e medição antes de decidir.</p></div><nav aria-label="Filtrar decisões" className="flex flex-wrap gap-2">{filters.map(([key, label]) => <Button key={key} size="sm" variant={source === key ? "primary" : "ghost"} onClick={() => setParam("source", key)}>{label}</Button>)}</nav></header>

    {bulk.size > 0 && (
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-[9px] border border-[var(--border)] bg-[var(--surface)] px-4 py-2 shadow-sm">
        <span className="text-sm">✓ {bulk.size} selecionado(s){selectedUrls.length !== bulk.size ? ` · ${selectedUrls.length} com URL delegável` : ""}</span>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setBulk(new Set())}>Limpar</Button>
          {canReview && <Button size="sm" onClick={() => resolve.mutate(selectedUrls)} disabled={selectedUrls.length === 0 || resolve.isPending}>Delegar melhorias</Button>}
        </div>
      </div>
    )}

    <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]">
      <table className="w-full text-sm">
        <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
          <tr><th className="w-8 px-3 py-2"><span className="sr-only">Selecionar</span></th><th className="px-3 py-2">Decisão</th><th className="px-3 py-2">Evidência principal</th><th className="px-3 py-2">Classe</th><th className="px-3 py-2">Prioridade</th></tr>
        </thead>
        <tbody>
          {visible.map((item) => {
            const view = presentOpportunity(item);
            return <tr key={item.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
              <td className="px-3 py-2"><input type="checkbox" checked={bulk.has(item.id)} disabled={!item.url || !canReview} onChange={() => toggleBulk(item.id)} aria-label={`Selecionar ${displayTitle(item)}`} /></td>
              <td className="max-w-2xl px-3 py-2"><button onClick={() => setParam("item", item.id)} className="block max-w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"><span className="block text-xs font-medium text-[var(--primary)]">{view.label}</span><span className="mt-0.5 block line-clamp-1 font-medium">{displayTitle(item)}</span><span className="mt-0.5 block line-clamp-1 text-xs font-normal text-[var(--muted)]">{view.detail}</span></button></td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-[var(--muted)]">{opportunityEvidenceSummary(item)}</td>
              <td className="px-3 py-2"><ActionBadge value={item.action_class} /></td>
              <td className="px-3 py-2 tabular-nums">{formatPriority(item.score)}</td>
            </tr>;
          })}
          {!items.length && <tr><td colSpan={5} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma decisão nesta visão.</td></tr>}
        </tbody>
      </table>
      <Pagination page={page} pageSize={pageSize} total={items.length} onPageChange={(next) => { setPage(next); setParam("page", String(next)); }} label="decisões" />
    </div>
    {!canReview && bulk.size > 0 && <p className="text-xs text-[var(--muted)]">🔒 Você pode inspecionar, mas não possui permissão (opportunity.review) para selecionar em lote.</p>}
    {selected && <Detail item={selected} canReview={canReview} pending={decision.isPending} error={decision.error} close={() => setParam("item", "")} decide={(action) => decision.mutate({ id: selected.id, action })} />}
    {delegateFps != null && <DelegateCampaignModal fingerprints={delegateFps} onClose={() => setDelegateFps(null)} onCreated={() => { setDelegateFps(null); setBulk(new Set()); queryClient.invalidateQueries({ queryKey: ["campaigns"] }); }} />}
  </div>;
}

function Detail({ item, canReview, pending, error, close, decide }: { item: Opportunity; canReview: boolean; pending: boolean; error: Error | null; close: () => void; decide: (action: Decision) => void }) {
  const view = presentOpportunity(item);
  const extras = item.related_recommendations ?? [];
  const heading = item.source === "interlink" && item.link_context?.target_title ? `Adicionar link para ${cleanTitle(item.link_context.target_title)}` : displayTitle(item);
  return <Drawer title="Decisão de melhoria" onClose={close}><div className="mb-5 flex justify-between gap-3"><div className="min-w-0"><ActionBadge value={item.action_class} /><p className="mt-2 text-sm font-medium text-[var(--primary)]">{view.label}</p><h2 className="mt-1 text-xl font-bold leading-snug">{heading}</h2><p className="mt-2 text-sm font-normal leading-6 text-[var(--muted)]">{view.detail}</p></div><Button variant="ghost" size="sm" onClick={close}>Fechar</Button></div><DecisionInsight item={item} /><section className="mt-5 text-sm" aria-labelledby="action-title"><h3 id="action-title" className="font-semibold">Escopo da melhoria</h3>{extras.length > 0 && <><h4 className="mt-3 font-medium">Ações complementares</h4><ul className="mt-1 list-disc space-y-1 pl-5">{extras.map((value) => <li key={value}>{value}</li>)}</ul></>}<div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"><strong>URL:</strong> <span className="break-all">{item.url || "a definir"}</span></div></section><div className="sticky bottom-0 -mx-6 mt-6 border-t border-[var(--border)] bg-[var(--surface)] px-6 pt-4"><p className="mb-3 text-xs text-[var(--muted)]">{canReview ? "Aprovar registra o plano; implementação e medição continuam rastreadas separadamente." : "Você não possui permissão para decidir esta oportunidade."}</p><div className="flex flex-wrap justify-end gap-2"><Button variant="secondary" disabled={!canReview || pending} onClick={() => decide("reject")}>Rejeitar</Button><Button variant="secondary" disabled={!canReview || pending} onClick={() => decide("snooze")}>Adiar</Button><Button disabled={!canReview || pending} onClick={() => decide("approve")}>{pending ? "Registrando…" : "Aprovar plano"}</Button></div>{error && <p className="mt-2 text-sm text-[var(--danger)]">{error.message}</p>}</div></Drawer>;
}

function ActionBadge({ value }: { value: Opportunity["action_class"] }) { const content = value === "safe_fix" ? ["Correção segura", "success"] : value === "observe" ? ["Observar", "info"] : ["Requer aprovação", "warning"]; return <Badge tone={content[1] as "success" | "info" | "warning"}>{content[0]}</Badge>; }
function formatPriority(value: number | null) { if (value === null) return "—"; return value <= 1 ? `${Math.round(value * 100)}%` : value.toLocaleString("pt-BR", { maximumFractionDigits: 1 }); }
function cleanTitle(value: string) { return value.replace(/\s+[—|-]\s+UnicornioHater$/i, "").trim(); }
function displayTitle(item: Opportunity) {
  const title = item.title?.trim();
  if (title && title !== item.recommendation?.trim()) return cleanTitle(title);
  try {
    const slug = decodeURIComponent(new URL(item.url).pathname.split("/").filter(Boolean).pop() ?? "");
    if (slug) return slug.replace(/[-_]+/g, " ").replace(/^./, (letter) => letter.toUpperCase());
  } catch { /* URL may be absent for editorial decisions. */ }
  return title || item.url || "Título não informado";
}
function Loading() { return <p className="text-sm text-[var(--muted)]">Carregando decisões…</p>; }
