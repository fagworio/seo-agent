"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, Agent, AgentRun, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";
import { Button } from "@/design-system/button";

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
    </div>
  );
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "partial") return "warning";
  if (status === "running" || status === "queued") return "info";
  return "neutral";
}
