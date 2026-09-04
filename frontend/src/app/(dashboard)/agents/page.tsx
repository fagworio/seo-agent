"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, Agent, AgentRun, ApiError, Campaign } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";
import { Button } from "@/design-system/button";
import { CampaignDetailDrawer } from "@/components/campaign-detail-drawer";

export default function AgentsPage() {
  const [intent, setIntent] = useState<"normal_cycle" | "technical" | "sitemap_indexing" | "opportunities" | "content" | "specific_url">("normal_cycle");
  const [mode, setMode] = useState<"analyze" | "safe_fix">("analyze");
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const { data, error, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api.get<{ agents: Agent[] }>("/agents"),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.get<{ runs: AgentRun[] }>("/runs?limit=50"),
  });
  const queue = useMutation({
    mutationFn: () => api.post<{ ok: boolean; run: AgentRun }>("/runs", { intent, mode }, me.data?.csrf_token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.get<{ campaigns: Campaign[] }>("/campaigns"),
  });
  const campaignAction = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "pause" | "resume" | "cancel" }) =>
      api.post<Campaign>(`/campaigns/${id}/${action}`, {}, me.data?.csrf_token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
  });

  if (isLoading || runs.isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error || runs.error) {
    const e = (error ?? runs.error) as ApiError;
    return <div className="text-sm text-[var(--danger)]">{e.message}</div>;
  }

  const agents = data!.agents;
  const runList = runs.data!.runs;
  const canRun = me.data?.user.permissions.includes("agent.run") ?? false;
  const byStatus = { running: runList.filter((r) => r.status === "running" || r.status === "queued"),
                     failed: runList.filter((r) => r.status === "failed" || r.status === "partial"),
                     recent: runList.filter((r) => !["running", "queued", "failed", "partial"].includes(r.status)) };

  return (
    <div className="space-y-6">
      <Card title="Solicitar execução">
        <p className="mb-3 text-sm text-[var(--muted)]">A solicitação entra na fila; Hermes muda o estado para “em execução” quando o worker a assumir.</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">Intenção<select value={intent} onChange={(event) => setIntent(event.target.value as typeof intent)} className="mt-1 block h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3"><option value="normal_cycle">Ciclo normal</option><option value="technical">SEO técnico</option><option value="sitemap_indexing">Sitemap e indexação</option><option value="opportunities">Oportunidades</option><option value="content">Conteúdo</option><option value="specific_url">URL específica</option></select></label>
          <label className="text-sm">Modo<select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} className="mt-1 block h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3"><option value="analyze">Somente analisar</option><option value="safe_fix">Gerar safe fixes</option></select></label>
          <Button onClick={() => queue.mutate()} disabled={!canRun || queue.isPending}>{queue.isPending ? "Solicitando…" : "Solicitar execução"}</Button>
        </div>
        {!canRun && <p className="mt-2 text-xs text-[var(--muted)]">Você não possui a permissão para executar agentes.</p>}
        {queue.error && <p className="mt-2 text-sm text-[var(--danger)]">{(queue.error as ApiError).message}</p>}
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {agents.map((agent) => (
          <Card key={agent.id} title={agent.name}>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <Badge tone="success">● {agent.enabled ? "Healthy" : "Desativado"}</Badge>
                <span className="text-[var(--muted)]">{agent.description}</span>
              </span>
            </div>
          </Card>
        ))}
        {agents.length === 0 && (
          <div className="text-sm text-[var(--muted)]">Nenhum agente registrado.</div>
        )}
      </div>

      {[
        { label: "Em execução", items: byStatus.running, tone: "info" as const },
        { label: "Falhas / parciais", items: byStatus.failed, tone: "danger" as const },
        { label: "Recentes", items: byStatus.recent, tone: "neutral" as const },
      ].map((section) => (
        <Card key={section.label} title={section.label}>
          {section.items.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Nada aqui.</p>
          ) : (
            <ul className="space-y-2">
              {section.items.map((run) => (
                <li key={run.id} className="flex items-center justify-between text-sm">
                  <Link href={`/agents/runs/${run.id}`} className="truncate hover:text-[var(--primary)]">
                    {run.agent} · {run.intent ?? "-"}
                  </Link>
                  <span className="flex items-center gap-2 text-xs text-[var(--muted)]">
                    {run.started_at ?? ""} · {run.urls_analyzed} URLs · {run.findings_count} findings
                    <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ))}

      <CampaignsSection
        campaigns={campaigns.data?.campaigns ?? []}
        pending={campaignAction.isPending}
        onAction={(id, action) => campaignAction.mutate({ id, action })}
      />
    </div>
  );
}

function CampaignsSection({ campaigns, pending, onAction }: {
  campaigns: Campaign[];
  pending: boolean;
  onAction: (id: number, action: "pause" | "resume" | "cancel") => void;
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  return (
    <Card title="Campanhas">
      {campaigns.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">Nenhuma campanha. Selecione correções e use “Delegar melhorias”.</p>
      ) : (
        <ul className="space-y-4">
          {campaigns.map((c) => {
            const done = c.executed_items;
            const total = c.total_items || 1;
            const pct = Math.round((done / total) * 100);
            return (
              <li key={c.id} className="rounded-md border border-[var(--border)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-medium">{c.name}</div>
                    <div className="text-xs text-[var(--muted)]">{done} / {c.total_items} concluídas · {c.pending_items} pendentes{c.failed_items ? ` · ${c.failed_items} falhas` : ""}{c.stale_items ? ` · ${c.stale_items} stale` : ""}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={campaignTone(c.status)}>{c.status}</Badge>
                    <Button size="sm" variant="secondary" onClick={() => setOpenId(c.id)}>Abrir</Button>
                    {["paused"].includes(c.status) && <Button size="sm" variant="secondary" disabled={pending} onClick={() => onAction(c.id, "resume")}>Continuar</Button>}
                    {["approved", "queued", "running", "partial"].includes(c.status) && <Button size="sm" variant="secondary" disabled={pending} onClick={() => onAction(c.id, "pause")}>Pausar</Button>}
                    {!["cancelled", "completed", "measured"].includes(c.status) && <Button size="sm" variant="ghost" disabled={pending} onClick={() => onAction(c.id, "cancel")}>Cancelar</Button>}
                  </div>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--surface-raised)]">
                  <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${pct}%` }} />
                </div>
                <div className="mt-1 flex justify-between text-xs text-[var(--muted)]">
                  <span>Política: {c.max_actions_per_run} por ciclo</span>
                  {c.next_run_at && <span>Próxima: {c.next_run_at}</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {openId != null && <CampaignDetailDrawer campaignId={openId} onClose={() => setOpenId(null)} />}
    </Card>
  );
}

function campaignTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "completed" || status === "measured") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "partial") return "warning";
  if (status === "running" || status === "queued") return "info";
  if (status === "paused") return "neutral";
  return "neutral";
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "partial") return "warning";
  if (status === "running" || status === "queued") return "info";
  return "neutral";
}
