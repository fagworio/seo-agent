"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, Opportunity } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";

const FILTERS = [
  { key: "", label: "Todos" },
  { key: "checklist", label: "Checklist" },
  { key: "content_brief", label: "Content brief" },
  { key: "backlog", label: "Backlog" },
  { key: "interlink", label: "Interlink" },
];

type Decision = "approve" | "reject" | "snooze";

export default function WorkPage() {
  const [source, setSource] = useState("");
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const qc = useQueryClient();

  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") });
  const csrf = me.data?.csrf_token;

  const { data, error, isLoading } = useQuery({
    queryKey: ["work-items", source],
    queryFn: () => api.get<{ work_items: Opportunity[] }>(`/work-items?limit=200${source ? `&source=${source}` : ""}`),
  });

  const decision = useMutation({
    mutationFn: ({ id, action }: { id: string; action: Decision }) =>
      api.post<{ ok: boolean }>(`/work-items/${id}/${action}`, {}, csrf),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-items"] });
      setSelected(null);
    },
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const items = data!.work_items;

  return (
    <div className="flex h-full gap-6">
      <div className="min-w-0 flex-1 space-y-4">
        <div className="flex items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setSource(f.key)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                source === f.key
                  ? "bg-[var(--primary-soft)] text-[var(--primary)]"
                  : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
              <tr>
                <th className="px-3 py-2">Oportunidade</th>
                <th className="px-3 py-2">Fonte</th>
                <th className="px-3 py-2">Score</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => setSelected(item)}
                  className="cursor-pointer border-t border-[var(--border)] hover:bg-[var(--surface-raised)]"
                >
                  <td className="max-w-md truncate px-3 py-2">{item.title || item.url || item.id}</td>
                  <td className="px-3 py-2"><Badge tone="neutral">{item.source}</Badge></td>
                  <td className="px-3 py-2 tabular-nums">{String(item.score ?? "—")}</td>
                  <td className="px-3 py-2"><Badge tone="info">{item.status}</Badge></td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-[var(--muted)]">
                    Nenhum item para esta visão.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <aside className="w-96 shrink-0 rounded-[11px] border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="mb-2 flex items-center justify-between">
            <Badge tone="primary">{selected.source}</Badge>
            <button className="text-[var(--muted)]" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="mb-1 font-semibold">{selected.title || selected.url}</div>
          <div className="mb-4 text-xs text-[var(--muted)]">{selected.id}</div>

          <div className="mb-4">
            <div className="mb-1 text-xs font-medium text-[var(--muted)]">Evidência</div>
            <div className="text-sm">{selected.evidence || "—"}</div>
          </div>

          <div className="mb-4">
            <div className="mb-1 text-xs font-medium text-[var(--muted)]">Recomendação</div>
            <div className="text-sm">{selected.recommendation || "—"}</div>
          </div>

          <div className="mb-4">
            <div className="mb-1 text-xs font-medium text-[var(--muted)]">Classe de ação</div>
            <Badge tone="warning">Requer aprovação</Badge>
          </div>

          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => decision.mutate({ id: selected.id, action: "reject" })}>
              Rejeitar
            </Button>
            <Button variant="secondary" onClick={() => decision.mutate({ id: selected.id, action: "snooze" })}>
              Adiar
            </Button>
            <Button onClick={() => decision.mutate({ id: selected.id, action: "approve" })}>
              Aprovar
            </Button>
          </div>
          {decision.error && <p className="mt-2 text-sm text-[var(--danger)]">{(decision.error as Error).message}</p>}
        </aside>
      )}
    </div>
  );
}
