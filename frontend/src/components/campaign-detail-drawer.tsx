"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Campaign } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";

type CampaignItem = {
  id: number;
  work_item_id: string | null;
  action_fingerprint: string;
  url: string;
  action_type: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  fix: Record<string, unknown>;
  status: string;
  failure_reason: string;
  executed_run_id: number | null;
  executed_at: string | null;
  verified_at: string | null;
};

type CampaignDetail = Campaign & { items: CampaignItem[] };

const STATUS_LABELS: Record<string, string> = {
  pending: "Pendente",
  executed: "Implementado",
  failed: "Falhou",
  stale: "Precisa revisão",
  skipped: "Ignorado",
};

export function CampaignDetailDrawer({ campaignId, onClose }: { campaignId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const detail = useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => api.get<CampaignDetail>(`/campaigns/${campaignId}`),
  });
  const action = useMutation({
    mutationFn: (kind: "run" | "pause" | "resume" | "cancel") =>
      api.post<CampaignDetail>(`/campaigns/${campaignId}/${kind}`, {}, me.data?.csrf_token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaign", campaignId, "campaigns"] }),
  });

  const canRun = me.data?.user.permissions.includes("agent.run") ?? false;
  if (detail.isLoading) return <Drawer title="Campanha" onClose={onClose}><p className="text-sm text-[var(--muted)]">Carregando…</p></Drawer>;
  if (detail.isError || !detail.data) return <Drawer title="Campanha" onClose={onClose}><p className="text-sm text-[var(--danger)]">{(detail.error as Error)?.message ?? "Campanha não encontrada."}</p></Drawer>;

  const c = detail.data;
  const total = c.total_items || 1;
  const pct = Math.round((c.executed_items / total) * 100);
  const canPause = ["approved", "queued", "running", "partial"].includes(c.status);
  const canResume = c.status === "paused";
  const canCancel = !["cancelled", "completed", "measured"].includes(c.status);

  return (
    <Drawer title={c.name} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div className="flex items-center justify-between">
          <Badge tone={campaignTone(c.status)}>{c.status}</Badge>
          <span className="text-xs text-[var(--muted)]">{c.executed_items} / {c.total_items} concluídas · {c.pending_items} pendentes{c.failed_items ? ` · ${c.failed_items} falhas` : ""}</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-raised)]">
          <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${pct}%` }} />
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted)]">
          <span>Modo: <strong className="text-[var(--foreground)]">{c.execution_mode === "now" ? "Executar agora" : "Hermes"}</strong></span>
          <span>Limite: <strong className="text-[var(--foreground)]">{c.max_actions_per_run}/ciclo</strong></span>
          <span>Criada por: <strong className="text-[var(--foreground)]">{c.created_by || "—"}</strong></span>
          {c.next_run_at && <span>Próxima: <strong className="text-[var(--foreground)]">{c.next_run_at}</strong></span>}
        </div>

        <div className="flex flex-wrap gap-2">
          {canRun && c.pending_items > 0 && (
            <Button size="sm" onClick={() => action.mutate("run")} disabled={action.isPending}>Executar próximo lote</Button>
          )}
          {canPause && <Button size="sm" variant="secondary" onClick={() => action.mutate("pause")} disabled={action.isPending}>Pausar</Button>}
          {canResume && <Button size="sm" variant="secondary" onClick={() => action.mutate("resume")} disabled={action.isPending}>Retomar</Button>}
          {canCancel && <Button size="sm" variant="ghost" onClick={() => action.mutate("cancel")} disabled={action.isPending}>Cancelar</Button>}
        </div>
        {action.isError && <p className="text-xs text-[var(--danger)]">{(action.error as Error).message}</p>}

        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Itens ({c.items.length})</div>
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {c.items.map((it) => (
              <li key={it.id} className="flex items-center justify-between gap-2 rounded-md border border-[var(--border)] px-3 py-2">
                <span className="truncate text-xs text-[var(--muted)]">{shortUrl(it.url)}</span>
                <span className="flex items-center gap-2">
                  {it.failure_reason && <span className="max-w-40 truncate text-[11px] text-[var(--muted)]">{it.failure_reason}</span>}
                  <Badge tone={itemTone(it.status)}>{STATUS_LABELS[it.status] ?? it.status}</Badge>
                </span>
              </li>
            ))}
            {c.items.length === 0 && <li className="text-xs text-[var(--muted)]">Nenhum item.</li>}
          </ul>
        </div>
      </div>
    </Drawer>
  );
}

function campaignTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "completed" || status === "measured") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "partial") return "warning";
  if (status === "running" || status === "queued") return "info";
  return "neutral";
}

function itemTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "executed") return "success";
  if (status === "failed") return "danger";
  if (status === "stale") return "warning";
  if (status === "skipped") return "neutral";
  return "info";
}

function shortUrl(u: string): string {
  const path = u.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const parts = path.split("/");
  return parts.length > 1 ? `/${parts.slice(1).join("/")}` : u;
}
