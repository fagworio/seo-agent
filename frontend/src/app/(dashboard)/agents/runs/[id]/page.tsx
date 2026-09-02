"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, RunDetail } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

const TABS = ["Summary", "Stages", "Results", "Changes", "Logs"] as const;

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Summary");

  const { data, error, isLoading } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<{ run: RunDetail }>(`/runs/${id}`),
    // polling 3s só enquanto queued|running; para em estados terminais (ADR-0007)
    refetchInterval: (q) => {
      const status = (q.state.data as { run?: RunDetail } | undefined)?.run?.status;
      return status === "queued" || status === "running" ? 3000 : false;
    },
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const run = data!.run;
  const chips: Record<string, string> = {
    Summary: `${run.summary?.ok === undefined ? "Resumo" : "Resumo"} · ${run.agent}`,
    Stages: `${run.steps.length} etapas`,
    Results: `${run.findings_count} findings · ${run.opportunities_count} ops`,
    Changes: run.comparison ? `delta vs ${run.comparison.prior_run_id}` : "sem comparável",
    Logs: `${run.events.length} eventos`,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">{run.agent}</h1>
        <Badge tone={statusTone(run.status)}>{run.status}</Badge>
        <span className="text-sm text-[var(--muted)]">
          {run.trigger} · {run.intent ?? "-"} · iniciado por {run.started_by ?? "system"}
        </span>
        {run.duration_ms != null && (
          <span className="text-sm text-[var(--muted)]">{run.duration_ms / 1000}s</span>
        )}
      </div>

      <div className="flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${
              tab === t ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <Card title={chips[tab] ?? tab}>
        {tab === "Summary" && (
          <div className="space-y-2 text-sm">
            <div className="flex gap-6">
              <Metric label="URLs" value={run.urls_analyzed} />
              <Metric label="Findings" value={run.findings_count} />
              <Metric label="Oportunidades" value={run.opportunities_count} />
              <Metric label="Safe fixes" value={run.safe_fixes_count} />
              <Metric label="Executados" value={run.executed_changes_count} />
            </div>
            {run.error && <p className="text-sm text-[var(--danger)]">Erro: {run.error}</p>}
            {run.summary && <pre className="whitespace-pre-wrap text-xs text-[var(--muted)]">{JSON.stringify(run.summary, null, 2)}</pre>}
            {!run.summary && <p className="text-[var(--muted)]">Sem resumo humano.</p>}
          </div>
        )}

        {tab === "Stages" && (
          <ul className="space-y-2">
            {run.steps.map((step, i) => (
              <li key={i} className="flex items-center justify-between text-sm">
                <span>{step.stage}</span>
                <span className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  {step.duration_ms != null && `${step.duration_ms / 1000}s`}
                  <Badge tone={statusTone(step.status)}>{step.status}</Badge>
                </span>
              </li>
            ))}
            {run.steps.length === 0 && <p className="text-sm text-[var(--muted)]">Sem etapas registradas.</p>}
          </ul>
        )}

        {tab === "Results" && (
          <p className="text-sm">
            <span className="tabular-nums">{run.findings_count}</span> findings ·{" "}
            <span className="tabular-nums">{run.opportunities_count}</span> oportunidades ·{" "}
            <span className="tabular-nums">{run.safe_fixes_count}</span> safe fixes.
          </p>
        )}

        {tab === "Changes" && (
          <pre className="whitespace-pre-wrap text-xs text-[var(--muted)]">
            {JSON.stringify(run.comparison, null, 2) ?? "Sem execução comparável."}
          </pre>
        )}

        {tab === "Logs" && (
          <ul className="max-h-96 space-y-1 overflow-auto font-mono text-xs">
            {run.events.map((e, i) => (
              <li key={i} className={e.level === "error" ? "text-[var(--danger)]" : "text-[var(--muted)]"}>
                {e.ts} [{e.level}] {e.event} {e.message ?? ""}
              </li>
            ))}
            {run.events.length === 0 && <li className="text-[var(--muted)]">Sem logs.</li>}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-[var(--muted)]">{label}</div>
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
