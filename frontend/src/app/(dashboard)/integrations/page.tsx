"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError, IntegrationSource } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

export default function IntegrationsPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.get<{ integrations: IntegrationSource[] }>("/integrations"),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const sources = data!.integrations;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {sources.map((s) => (
        <Card key={s.source} title={s.source}>
          <div className="mb-3 flex items-center justify-between">
            <Badge tone={statusTone(s.data_status)}>{s.data_status}</Badge>
            <span className="text-xs text-[var(--muted)]">{s.configured ? "configurado" : "não configurado"}</span>
          </div>
          <dl className="space-y-1 text-sm">
            <Row k="Detalhe" v={s.detail} />
            <Row k="Última janela" v={s.last_window || "—"} />
            <Row k="Linhas" v={String(s.rows)} />
            {typeof s.documents === "number" && <Row k="Documentos" v={String(s.documents)} />}
            {typeof s.global_coverage_pct === "number" && <Row k="Cobertura" v={`${s.global_coverage_pct}%`} />}
            {typeof s.provider === "string" && <Row k="Provedor" v={s.provider} />}
          </dl>
          {s.limitations && <p className="mt-3 text-xs text-[var(--muted)]">Limitação: {s.limitations}</p>}
        </Card>
      ))}
      {sources.length === 0 && (
        <div className="text-sm text-[var(--muted)]">Nenhuma fonte configurada.</div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[var(--muted)]">{k}</dt>
      <dd className="max-w-[60%] truncate tabular-nums">{v}</dd>
    </div>
  );
}

function statusTone(s: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (s === "available") return "success";
  if (s === "partial") return "warning";
  if (s === "missing" || s === "invalid") return "danger";
  return "neutral";
}
