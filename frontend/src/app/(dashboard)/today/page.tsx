"use client";

import { useQuery } from "@tanstack/react-query";
import { api, TodayResponse, ApiError } from "@/lib/api";
import { Card } from "@/design-system/card";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import Link from "next/link";

export default function TodayPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["today"],
    queryFn: () => api.get<TodayResponse>("/dashboard/today?limit=5"),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) {
    const apiErr = error as ApiError;
    if (apiErr.status === 401) {
      return (
        <Card className="mx-auto max-w-md text-center">
          <div className="mb-2 text-sm font-semibold">Não autenticado</div>
          <p className="mb-4 text-sm text-[var(--muted)]">
            Entre para ver o painel de operações.
          </p>
          <Link href="/login">
            <Button>Ir para o login</Button>
          </Link>
        </Card>
      );
    }
    return <div className="text-sm text-[var(--danger)]">{apiErr.message}</div>;
  }

  const t = data!.today;
  return (
    <div className="space-y-6">
      {/* Atenção em primeiro lugar (never BI) */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard label="Precisa de atenção" value={t.needs_attention} tone="primary" />
        <KpiCard label="Findings críticos" value={t.critical_findings} tone="danger" />
        <KpiCard label="Safe fixes" value={t.safe_fixes} tone="success" />
        <KpiCard label="Runs recentes" value={t.recent_runs.length} tone="info" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Execuções recentes">
          {t.recent_runs.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Nenhuma execução registrada.</p>
          ) : (
            <ul className="space-y-2">
              {t.recent_runs.map((run) => (
                <li key={run.id} className="flex items-center justify-between text-sm">
                  <span className="truncate">{run.agent}</span>
                  <span className="flex items-center gap-2 text-xs text-[var(--muted)]">
                    {run.intent ?? "-"} <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Top oportunidades">
          {t.top_opportunities.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Sem oportunidades no momento.</p>
          ) : (
            <ul className="space-y-2">
              {t.top_opportunities.map((op) => (
                <li key={op.id} className="flex items-center justify-between text-sm">
                  <span className="truncate">{op.title || op.url}</span>
                  <span className="flex items-center gap-2">
                    <Badge tone="neutral">{op.source}</Badge>
                    <span className="tabular-nums text-xs">{String(op.score ?? "—")}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Saúde das fontes">
        <ul className="space-y-1">
          {t.integration_warnings.map((src) => (
            <li key={src.source} className="flex items-center justify-between text-sm">
              <span>{src.source}</span>
              <Badge tone={"warning"}>{src.data_status}</Badge>
            </li>
          ))}
          {t.integration_warnings.length === 0 && (
            <li className="text-sm text-[var(--muted)]">Todas as fontes disponíveis.</li>
          )}
        </ul>
      </Card>
    </div>
  );
}

function KpiCard({ label, value, tone }: { label: string; value: number; tone: "primary" | "danger" | "success" | "info" }) {
  return (
    <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="text-2xl font-semibold tabular-nums" style={{ color: `var(--${tone})` }}>
        {value}
      </div>
      <div className="text-xs text-[var(--muted)]">{label}</div>
    </div>
  );
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "partial") return "warning";
  if (status === "running") return "info";
  return "neutral";
}
