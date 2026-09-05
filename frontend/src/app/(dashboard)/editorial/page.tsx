"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { Drawer } from "@/design-system/drawer";
import { Pagination, pageSlice } from "@/components/pagination";
import { guideOf, intentLabel } from "./guide";

type Item = { id: string; type: string; title: string; intent: string; evidence: string; related_urls: string[]; recommendation: string; duplication_risk: string; score: number | null; status: string; published_url: string; responsible: string };

const columns = [["proposed", "Para revisar", "warning"], ["approved", "Aprovadas", "primary"], ["published", "Publicadas", "info"], ["measured", "Medidas", "success"]] as const;
const size = 6;

export default function EditorialPage() {
  const [selected, setSelected] = useState<Item | null>(null); const [publishedUrl, setPublishedUrl] = useState(""); const [pages, setPages] = useState<Record<string, number>>({});
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const query = useQuery({ queryKey: ["editorial"], queryFn: () => api.get<{ items: Item[] }>("/editorial?limit=200") });
  const transition = useMutation({ mutationFn: ({ id, action }: { id: string; action: string }) => api.post<{ ok: boolean }>(`/editorial/${id}/${action}`, action === "publish" ? { published_url: publishedUrl } : {}, me.data?.csrf_token), onSuccess: () => { qc.invalidateQueries({ queryKey: ["editorial"] }); setSelected(null); } });
  if (query.isLoading) return <p className="text-sm text-[var(--muted)]">Carregando pipeline editorial…</p>;
  if (query.error) return <p className="text-sm text-[var(--danger)]">{(query.error as ApiError).message}</p>;
  const items = query.data?.items ?? []; const waiting = items.filter((item) => item.status === "proposed").length;
  const canReview = me.data?.user.permissions.includes("editorial.review") ?? false; const canPublish = me.data?.user.permissions.includes("editorial.publish_confirm") ?? false;
  return <div className="space-y-5"><header className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-xl font-semibold">Pipeline editorial</h1><p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">Descubra oportunidades de conteúdo, aprove a pauta, publique com confirmação humana e acompanhe o resultado.</p></div><div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm"><strong className="tabular-nums">{waiting}</strong><span className="ml-1 text-[var(--muted)]">pautas aguardando sua decisão</span></div></header><div className="rounded-[9px] border border-[var(--border)] bg-[var(--primary-soft)] px-4 py-3 text-sm"><strong>Como funciona:</strong> o agente reúne as evidências → você decide (aprovar / adiar / rejeitar) → a pauta vai para <em>Aprovadas</em> → você confirma a publicação → o sistema mede o resultado.</div><div className="grid gap-4 xl:grid-cols-4">{columns.map(([status, title, tone]) => { const cards = items.filter((item) => item.status === status); const page = pages[status] ?? 1; return <Card key={status} className="flex min-h-[20rem] flex-col" title={<div className="flex items-center justify-between"><span>{title}</span><Badge tone={tone}>{cards.length}</Badge></div>}><ul className="space-y-2">{pageSlice(cards, page, size).map((item) => { const guide = guideOf(item.type); return <li key={item.id}><button onClick={() => { setSelected(item); setPublishedUrl(item.published_url); }} className="w-full rounded-md border border-[var(--border)] p-3 text-left hover:bg-[var(--surface-raised)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"><Badge tone={guide.tone} className="mb-2 text-[11px]">{guide.label}</Badge><div className="truncate font-medium">{item.title || "Sem título"}</div><div className="mt-1 line-clamp-1 text-xs text-[var(--muted)]">{guide.hint}</div><div className="mt-2 flex justify-between gap-2 text-xs text-[var(--muted)]"><span className="truncate">{item.type || "Pauta"}</span><span className="tabular-nums">Score {item.score ?? "—"}</span></div>{item.responsible && <p className="mt-1 truncate text-xs text-[var(--muted)]">Responsável: {item.responsible}</p>}</button></li>; })}{!cards.length && <li className="rounded-md border border-dashed border-[var(--border)] p-3 text-sm text-[var(--muted)]">Nenhum item neste estágio.</li>}</ul>{cards.length > size && <div className="mt-auto pt-3"><Pagination page={page} pageSize={size} total={cards.length} onPageChange={(next) => setPages((current) => ({ ...current, [status]: next }))} label="itens" /></div>}</Card>; })}</div>{selected && <ItemDrawer item={selected} publishedUrl={publishedUrl} setPublishedUrl={setPublishedUrl} canReview={canReview} canPublish={canPublish} pending={transition.isPending} error={transition.error} close={() => setSelected(null)} action={(action) => transition.mutate({ id: selected.id, action })} />}</div>;
}

function ItemDrawer({ item, publishedUrl, setPublishedUrl, canReview, canPublish, pending, error, close, action }: { item: Item; publishedUrl: string; setPublishedUrl: (value: string) => void; canReview: boolean; canPublish: boolean; pending: boolean; error: Error | null; close: () => void; action: (value: string) => void }) {
  const guide = guideOf(item.type);
  return <Drawer title="Decisão editorial" onClose={close}><div className="flex justify-between gap-3"><div><Badge tone="warning">{item.status}</Badge><h2 className="mt-2 text-lg font-semibold">{item.title}</h2></div><Button size="sm" variant="ghost" onClick={close}>Fechar</Button></div>
    <section className="mt-5 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-4 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2"><Badge tone={guide.tone}>{guide.label}</Badge><span className="text-xs text-[var(--muted)]">{guide.hint}</span></div>
      <p className="mt-1 leading-6 text-[var(--muted)]">{guide.what}</p>
      <p className="mt-2 leading-6"><strong>Como fazer (na prática):</strong> {guide.how}</p>
    </section>
    <section className="mt-5 space-y-4 text-sm"><Detail label="O que a busca quer (intenção)" value={intentLabel(item.intent)} /><Detail label="Por que o agente sugeriu" value={item.evidence} /><Detail label="O que fazer" value={item.recommendation} /><Detail label="Risco de duplicar conteúdo" value={item.duplication_risk} /><Detail label="Páginas relacionadas" value={item.related_urls.join(", ")} /></section>
    <div className="sticky bottom-0 -mx-6 mt-6 border-t border-[var(--border)] bg-[var(--surface)] px-6 pt-4"><p className="mb-3 text-xs text-[var(--muted)]">{canReview || canPublish ? "A transição será registrada no histórico." : "Você não possui permissão para esta etapa."}</p>{item.status === "proposed" && <div className="flex flex-wrap justify-end gap-2"><Button variant="secondary" disabled={!canReview || pending} onClick={() => action("reject")}>Rejeitar</Button><Button variant="secondary" disabled={!canReview || pending} onClick={() => action("snooze")}>Adiar</Button><Button disabled={!canReview || pending} onClick={() => action("approve")}>Aprovar</Button></div>}{item.status === "approved" && <div><label className="text-sm font-medium">URL publicada<input value={publishedUrl} onChange={(event) => setPublishedUrl(event.target.value)} placeholder="https://…" className="mt-1 block h-9 w-full rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3" /></label><Button className="mt-3" disabled={!canPublish || !publishedUrl || pending} onClick={() => action("publish")}>Confirmar publicação</Button></div>}{item.status === "published" && <Button disabled={!canPublish || pending} onClick={() => action("measure")}>Iniciar medição</Button>}{error && <p className="mt-3 text-sm text-[var(--danger)]">{error.message}</p>}</div></Drawer>;
}
function Detail({ label, value }: { label: string; value: string }) { return <div><h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">{label}</h3><p className="mt-1 leading-6">{value || "não informado"}</p></div>; }
