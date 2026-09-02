"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, Agent, AgentRun, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

export default function AgentsPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api.get<{ agents: Agent[] }>("/agents"),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.get<{ runs: AgentRun[] }>("/runs?limit=50"),
  });

  if (isLoading || runs.isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error || runs.error) {
    const e = (error ?? runs.error) as ApiError;
    return <div className="text-sm text-[var(--danger)]">{e.message}</div>;
  }

  const agents = data!.agents;
  const runList = runs.data!.runs;
  const byStatus = { running: runList.filter((r) => r.status === "running" || r.status === "queued"),
                     failed: runList.filter((r) => r.status === "failed" || r.status === "partial"),
                     recent: runList.filter((r) => !["running", "queued", "failed", "partial"].includes(r.status)) };

  return (
    <div className="space-y-6">
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
