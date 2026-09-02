"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, PageHistoryEntry } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

const TABS = ["Summary", "Search", "Content", "Links", "Technical", "History"] as const;

export default function PageWorkspace() {
  const params = useParams<{ id: string }>();
  const url = decodeURIComponent(params.id);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Summary");

  const { data, error, isLoading } = useQuery({
    queryKey: ["page-history", url],
    queryFn: () => api.get<{ url: string; history: PageHistoryEntry[] }>(`/pages/${params.id}/history`),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const history = data!.history;
  const latest = history[history.length - 1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{latest?.title || url}</h1>
        <span className="text-xs text-[var(--muted)]">{url}</span>
        {latest && <Badge tone={healthyTone(latest.status_code ?? 200)}>{String(latest.status_code ?? "—")}</Badge>}
      </div>

      <div className="flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Summary" && (
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
            <ul className="space-y-2 text-sm">
              <li><span className="text-[var(--muted)]">GSC:</span> {summary(latest?.gsc)}</li>
              <li><span className="text-[var(--muted)]">CWV:</span> {summary(latest?.cwv)}</li>
            </ul>
          </Card>
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
      {tab === "Links" && <Card title="Links"><p className="text-sm text-[var(--muted)]">Não há evidência de links associada a esta captura. Uma análise posterior poderá preencher esta área; ausência não equivale a ausência de links.</p></Card>}
      {tab === "Technical" && <Card title="SEO técnico"><dl className="space-y-2 text-sm"><Row label="Status HTTP" value={String(latest?.status_code ?? "não capturado")} /><Row label="Meta robots" value={latest?.meta_robots || "não capturado"} /><Row label="Canonical" value={latest?.canonical || "não capturado"} /></dl></Card>}
    </div>
  );
}

function summary(value: Record<string, unknown> | null | undefined) { return value ? Object.entries(value).map(([key, item]) => `${key}: ${String(item)}`).join(" · ") : "não capturado"; }
function Row({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">{label}</dt><dd className="max-w-[60%] truncate">{value}</dd></div>; }

function healthyTone(status: number): "success" | "warning" | "danger" {
  if (status >= 400) return "danger";
  if (status >= 300) return "warning";
  return "success";
}
