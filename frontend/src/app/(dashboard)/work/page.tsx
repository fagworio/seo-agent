"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api, ApiError, Opportunity } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";

const FILTERS = [
  { key: "", label: "Todos" }, { key: "checklist", label: "Checklist" },
  { key: "content_brief", label: "Content brief" }, { key: "backlog", label: "Backlog" },
  { key: "interlink", label: "Interlink" },
];
type Decision = "approve" | "reject" | "snooze";

export default function WorkPage() {
  return <Suspense fallback={<p className="text-sm text-[var(--muted)]">Carregando caixa de trabalho…</p>}><Workbox /></Suspense>;
}

function Workbox() {
  const router = useRouter();
  const params = useSearchParams();
  const source = params.get("source") ?? "";
  const selectedId = params.get("item");
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const { data, error, isLoading } = useQuery({
    queryKey: ["work-items", source],
    queryFn: () => api.get<{ work_items: Opportunity[] }>(`/work-items?limit=200${source ? `&source=${source}` : ""}`),
  });
  const items = data?.work_items ?? [];
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const canReview = me.data?.user.permissions.includes("opportunity.review") ?? false;
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    value ? next.set(key, value) : next.delete(key);
    router.replace(`/work?${next.toString()}`, { scroll: false });
  };
  const decision = useMutation({
    mutationFn: ({ id, action }: { id: string; action: Decision }) => api.post<{ ok: boolean }>(`/work-items/${id}/${action}`, {}, me.data?.csrf_token),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["work-items"] }); setParam("item", ""); },
  });

  if (isLoading) return <p className="text-sm text-[var(--muted)]">Carregando caixa de trabalho…</p>;
  if (error) return <p className="text-sm text-[var(--danger)]">{(error as ApiError).message}</p>;
  return <div className="space-y-4">
    <div className="flex flex-wrap gap-2" aria-label="Filtros da caixa de trabalho">
      {FILTERS.map((filter) => <Button key={filter.key} size="sm" variant={source === filter.key ? "primary" : "ghost"} onClick={() => setParam("source", filter.key)}>{filter.label}</Button>)}
    </div>
    <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]"><table className="w-full text-sm"><thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]"><tr><th className="px-3 py-2">Oportunidade</th><th className="px-3 py-2">Ação</th><th className="px-3 py-2">Score</th><th className="px-3 py-2">Estado</th></tr></thead><tbody>
      {items.map((item) => <tr key={item.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]"><td className="max-w-md px-3 py-2"><button className="max-w-full truncate text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]" onClick={() => setParam("item", item.id)}>{item.title || item.url || item.id}</button><span className="block truncate text-xs text-[var(--muted)]">{item.source}</span></td><td className="px-3 py-2"><ActionClass value={item.action_class} /></td><td className="px-3 py-2 tabular-nums">{item.score ?? "—"}</td><td className="px-3 py-2"><Badge tone="info">{item.status}</Badge></td></tr>)}
      {items.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-[var(--muted)]">Nenhum item para esta visão.</td></tr>}</tbody></table></div>
    {selected && <OpportunityDrawer item={selected} canReview={canReview} pending={decision.isPending} error={decision.error} onClose={() => setParam("item", "")} onDecision={(action) => decision.mutate({ id: selected.id, action })} />}
  </div>;
}

function ActionClass({ value }: { value: Opportunity["action_class"] }) {
  const meta = value === "safe_fix" ? ["Safe Fix", "success"] : value === "observe" ? ["Observar", "info"] : ["Requer aprovação", "warning"];
  return <Badge tone={meta[1] as "success" | "info" | "warning"}>{meta[0]}</Badge>;
}

function OpportunityDrawer({ item, canReview, pending, error, onClose, onDecision }: { item: Opportunity; canReview: boolean; pending: boolean; error: Error | null; onClose: () => void; onDecision: (action: Decision) => void }) {
  return <Drawer title="Detalhe da oportunidade" onClose={onClose}><div className="mb-5 flex items-start justify-between gap-4"><div><ActionClass value={item.action_class} /><h2 className="mt-2 text-lg font-semibold">{item.title || item.url}</h2><p className="text-xs text-[var(--muted)]">Score {item.score ?? "—"} · risco: {item.risk}</p></div><Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar detalhe">Fechar</Button></div><section className="mb-5"><h3 className="text-sm font-semibold">Por que importa</h3><p className="mt-1 text-sm">{item.evidence || "Evidência ainda não disponível."}</p></section><section className="mb-5"><h3 className="text-sm font-semibold">Recomendação</h3><p className="mt-1 text-sm">{item.recommendation || "Sem recomendação adicional."}</p></section><section className="mb-6 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm"><p>Escopo: {item.url || "a definir"}</p><p>Rollback: {item.rollback_available ? "disponível" : "não aplicável / não informado"}</p></section><div className="sticky bottom-0 -mx-6 border-t border-[var(--border)] bg-[var(--surface)] px-6 pt-4"><p className="mb-3 text-xs text-[var(--muted)]">{canReview ? "Sua decisão será registrada no histórico." : "Você não possui permissão para revisar esta oportunidade."}</p><div className="flex flex-wrap justify-end gap-2"><Button variant="secondary" onClick={() => onDecision("reject")} disabled={!canReview || pending}>Rejeitar</Button><Button variant="secondary" onClick={() => onDecision("snooze")} disabled={!canReview || pending}>Adiar</Button><Button onClick={() => onDecision("approve")} disabled={!canReview || pending}>{pending ? "Registrando…" : "Aprovar"}</Button></div>{error && <p className="mt-2 text-sm text-[var(--danger)]">{error.message}</p>}</div></Drawer>;
}
