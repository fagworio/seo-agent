"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, PageHistoryEntry } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { ScoreBar, ConfidenceBadge, MissingData, TechnicalEligibility } from "@/features/intelligence";

const TABS = ["Summary", "Search", "Content", "Links", "Technical", "History"] as const;

export default function PageWorkspace() {
  const params = useParams<{ id: string }>();
  const url = decodeURIComponent(params.id);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Summary");
  const qc = useQueryClient();

  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const canRun = me.data?.user.permissions.includes("agent.run") ?? false;
  const analyzePage = useMutation({
    mutationFn: () => api.post<{ id: number; status: string }>("/runs", { intent: "specific_url", target_url: url }, me.data?.csrf_token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const { data, error, isLoading } = useQuery({
    queryKey: ["page-history", url],
    queryFn: () => api.get<{ url: string; history: PageHistoryEntry[]; intelligence?: { index_state?: string; metrics?: { position?: number | null; clicks?: number; impressions?: number; ctr?: number | null }; rankability_v2?: { topic_authority?: { score?: number; label?: string }; headroom?: { score?: number }; opportunity?: { score?: number; label?: string }; confidence?: { score?: number; label?: string }; signals?: { posts?: number; momentum_delta_pct?: number | null } } } }>(`/pages/history?url=${encodeURIComponent(url)}`),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const history = data!.history;
  const latest = history[history.length - 1];
  const intelligence = data?.intelligence;
  const v2 = intelligence?.rankability_v2;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{latest?.title || url}</h1>
        <span className="text-xs text-[var(--muted)]">{url}</span>
        {latest && <Badge tone={healthyTone(latest.status_code ?? 200)}>{String(latest.status_code ?? "—")}</Badge>}
        <div className="ml-auto">
          <Button size="sm" variant="secondary" onClick={() => analyzePage.mutate()} disabled={!canRun || analyzePage.isPending}>
            {analyzePage.isPending ? "Solicitando…" : "Atualizar análise"}
          </Button>
        </div>
      </div>
      {analyzePage.isSuccess && <p className="text-xs text-[var(--success)]">Análise solicitada para esta página (execução #{(analyzePage.data as { id: number })?.id}). Acompanhe em Agentes & Execuções.</p>}
      {analyzePage.isError && <p className="text-xs text-[var(--danger)]">{(analyzePage.error as Error).message}</p>}

      <div className="flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Summary" && (
        <div className="space-y-4">
          <Card title="Inteligência desta página (V2)">
            {noindexGate(intelligence) ? (
              <TechnicalEligibility blocked={["Não indexável (noindex)"]} />
            ) : v2 ? (
              <div className="space-y-4">
                <div className="grid gap-1.5">
                  {typeof v2.topic_authority?.score === "number" && <ScoreBar label="Topic Authority" score={v2.topic_authority.score} level={v2.topic_authority.label} />}
                  {typeof intelligence?.metrics?.position === "number" && <ScoreBar label="Headroom" score={v2.headroom?.score ?? null} />}
                  {v2.opportunity && typeof v2.opportunity.score === "number" && <ScoreBar label="Oportunidade" score={v2.opportunity.score} level={v2.opportunity.label} />}
                  {v2.confidence && <div className="pt-1"><ConfidenceBadge score={v2.confidence.score} label={v2.confidence.label} /></div>}
                </div>
                {v2.opportunity?.score != null && v2.opportunity.score >= 70 && (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm">
                    <strong>↑ Oportunidade forte</strong>
                    <p className="mt-1 text-[var(--muted)]">Posição {String(intelligence?.metrics?.position ?? "—")} · autoridade {v2.topic_authority?.score ?? "—"} no tópico. Recomendado: <em>expandir conteúdo</em>.</p>
                  </div>
                )}
                <p className="text-xs text-[var(--muted)]">Dados usados: GSC · Corpus · Links internos. Janela: últimos 28 dias.</p>
              </div>
            ) : (
              <MissingData label="Dados insuficientes" detail="Esta página não resolve para um tópico do cluster (ou o corpus ainda não cobre o assunto). Os scores compostos ficam indisponíveis até haver base." />
            )}
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card title="Estado atual">
              <ul className="space-y-2 text-sm">
                <li><span className="text-[var(--muted)]">Title:</span> {latest?.title || "—"}</li>
                <li><span className="text-[var(--muted)]">Meta robots:</span> {latest?.meta_robots || "—"}</li>
                <li><span className="text-[var(--muted)]">Fonte:</span> {latest?.source || "—"}</li>
                <li><span className="text-[var(--muted)]">Ação vinculada:</span> {latest?.linked_action || "—"}</li>
              </ul>
            </Card>
            <Card title="Métricas (última captura)">
              <dl className="space-y-2 text-sm">
                <Row label="Posição" value={String(intelligence?.metrics?.position ?? "—")} />
                <Row label="Cliques" value={String(intelligence?.metrics?.clicks ?? "—")} />
                <Row label="Impressões" value={String(intelligence?.metrics?.impressions ?? "—")} />
                <Row label="GSC" value={summary(latest?.gsc)} />
                <Row label="CWV" value={summary(latest?.cwv)} />
              </dl>
            </Card>
          </div>
        </div>
      )}

      {tab === "History" && (
        <Card title={`Histórico (${history.length})`}>
          <ol className="space-y-3">
            {history.map((h, i) => (
              <li key={i} className="relative border-l border-[var(--border)] pl-4">
                <div className="text-sm font-medium">{h.ts}</div>
                <div className="text-sm text-[var(--muted)]">
                  {h.source || "—"} · {h.linked_action || "sem ação vinculada"} · status {String(h.status_code ?? "—")}
                </div>
                {h.title && <div className="text-xs text-[var(--muted)]">{h.title}</div>}
              </li>
            ))}
            {history.length === 0 && <li className="text-sm text-[var(--muted)]">Sem histórico.</li>}
          </ol>
        </Card>
      )}

      {tab === "Search" && <Card title="Search"><p className="text-sm">{latest?.gsc ? summary(latest.gsc) : "Search Console não forneceu dados nesta captura; isso não representa zero."}</p></Card>}
      {tab === "Content" && <Card title="Conteúdo"><dl className="space-y-2 text-sm"><Row label="Título" value={latest?.title || "não capturado"} /><Row label="Meta robots" value={latest?.meta_robots || "não capturado"} /><Row label="Canonical" value={latest?.canonical || "não capturado"} /><Row label="Hash de conteúdo" value={latest?.content_hash || "não capturado"} /></dl></Card>}
      {tab === "Links" && <Card title="Links — Internal Authority"><InternalAuthority v2={v2} /></Card>}
      {tab === "Technical" && <Card title="SEO técnico"><TechnicalEligibility checks={technicalChecks(intelligence, latest)} /><dl className="mt-3 space-y-2 text-sm"><Row label="Status HTTP" value={String(latest?.status_code ?? "não capturado")} /><Row label="Meta robots" value={latest?.meta_robots || "não capturado"} /><Row label="Canonical" value={latest?.canonical || "não capturado"} /></dl></Card>}
    </div>
  );
}

function summary(value: Record<string, unknown> | null | undefined) { return value ? Object.entries(value).map(([key, item]) => `${key}: ${String(item)}`).join(" · ") : "não capturado"; }
function Row({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">{label}</dt><dd className="max-w-[60%] truncate">{value}</dd></div>; }
function noindexGate(intelligence?: { index_state?: string } | null) { return intelligence?.index_state === "noindex"; }
function InternalAuthority({ v2 }: { v2?: { topic_authority?: { score?: number; factors?: { internal_authority?: { score?: number; explanation?: string } } } } | null }) {
  const f = v2?.topic_authority?.factors?.internal_authority;
  return (
    <div className="space-y-3 text-sm">
      {f ? (
        <>
          <ScoreBar label="Autoridade interna" score={typeof f.score === "number" ? f.score * 100 : null} />
          <p className="text-[var(--muted)]">{f.explanation || "Autoridade interna calculada pelo PageRank local do link graph."}</p>
        </>
      ) : (
        <MissingData label="Autoridade interna indisponível" detail="O link graph interno ainda não cobre o cluster desta página." />
      )}
      <p className="text-xs text-[var(--muted)]">A autoridade interna é calculada localmente (PageRank sobre internal_links), sem API externa.</p>
    </div>
  );
}
function technicalChecks(intelligence?: { index_state?: string } | null, latest?: { status_code?: number | null; meta_robots?: string; canonical?: string; cwv?: Record<string, unknown> | null } | undefined) {
  const robots = (latest?.meta_robots ?? "").toLowerCase();
  const cwv = latest?.cwv as { lcp?: number } | undefined;
  return { indexable: intelligence?.index_state !== "noindex", http_ok: (latest?.status_code ?? 200) < 400, canonical_ok: !!latest?.canonical, in_sitemap: intelligence?.index_state !== "outside", robots: !robots.includes("noindex"), google_indexed: latest != null, cwv_ok: cwv?.lcp == null ? null : cwv.lcp <= 2.5 };
}

function healthyTone(status: number): "success" | "warning" | "danger" {
  if (status >= 400) return "danger";
  if (status >= 300) return "warning";
  return "success";
}
