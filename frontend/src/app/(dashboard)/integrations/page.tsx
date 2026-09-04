"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, IntegrationSource } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";

const SOURCE_LABELS: Record<string, string> = {
  wordpress: "WordPress",
  sitemap: "Sitemap",
  corpus: "Corpus editorial",
  gsc: "Google Search Console",
  ga4: "Google Analytics (GA4)",
  crux: "CrUX (Core Web Vitals)",
  external: "Fonte externa",
};

export default function IntegrationsPage() {
  const qc = useQueryClient();
  const [verifying, setVerifying] = useState<string | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.get<{ integrations: IntegrationSource[] }>("/integrations"),
  });
  const verify = useMutation({
    mutationFn: (source?: string) =>
      api.get<{ integrations: IntegrationSource[] }>(
        `/integrations?live=true${source ? `&source=${source}` : ""}`),
    onSuccess: (res) => {
      qc.setQueryData<{ integrations: IntegrationSource[] }>(["integrations"], (old) => {
        const bySource = new Map((old?.integrations ?? []).map((s) => [s.source, s]));
        for (const s of res.integrations) bySource.set(s.source, s);
        return { integrations: [...bySource.values()] };
      });
    },
    onSettled: () => setVerifying(null),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const sources = data!.integrations;
  const run = (source?: string) => { setVerifying(source ?? "all"); verify.mutate(source); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Fontes de dados</h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">
            Verificar conexão apenas testa acesso e configuração — <strong>não coleta dados</strong>.
            Para buscar novos dados, use “Atualizar dados” (uma execução do agente).
          </p>
        </div>
        <Button
          onClick={() => run()}
          disabled={verify.isPending}
          variant="secondary"
        >
          {verifying === "all" ? "Verificando…" : "Verificar todas"}
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {sources.map((s) => {
          const checking = verifying === s.source || verifying === "all";
          return (
            <Card key={s.source} title={SOURCE_LABELS[s.source] ?? s.source}>
              <div className="mb-3 flex items-center justify-between">
                <Badge tone={statusTone(s)}>{statusLabel(s)}</Badge>
                <span className="text-xs text-[var(--muted)]">{s.configured ? "configurado" : "não configurado"}</span>
              </div>
              <dl className="space-y-1 text-sm">
                <Row k="Detalhe" v={s.detail} />
                <Row k="Última janela" v={s.last_window || "—"} />
                <Row k="Registros" v={String(s.rows)} />
                {typeof s.documents === "number" && <Row k="Documentos" v={String(s.documents)} />}
                {typeof s.global_coverage_pct === "number" && <Row k="Cobertura" v={`${s.global_coverage_pct}%`} />}
                {typeof s.provider === "string" && <Row k="Provedor" v={s.provider} />}
              </dl>
              {s.recovery && (
                <div className="mt-3 rounded-[7px] border border-[var(--warning)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--foreground)]">
                  <div className="mb-1 font-medium text-[var(--warning)]">Como recuperar</div>
                  <p>{s.recovery}</p>
                </div>
              )}
              {s.limitations && <p className="mt-3 text-xs text-[var(--muted)]">Limitação: {s.limitations}</p>}
              <div className="mt-3 flex justify-end">
                <Button size="sm" variant="secondary" onClick={() => run(s.source)} disabled={verify.isPending}>
                  {checking ? "Verificando…" : "Verificar conexão"}
                </Button>
              </div>
            </Card>
          );
        })}
        {sources.length === 0 && (
          <div className="text-sm text-[var(--muted)]">Nenhuma fonte configurada.</div>
        )}
      </div>
      {verify.error && <p className="text-sm text-[var(--danger)]">{(verify.error as Error).message}</p>}
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

function statusLabel(s: IntegrationSource): string {
  if (!s.configured) return "Não configurado";
  if (s.data_status === "available") return "Disponível";
  if (s.data_status === "partial") return "Parcial";
  if (s.data_status === "invalid") return "Indisponível";
  if (s.data_status === "missing") return "Sem dados";
  return s.data_status;
}

function statusTone(s: IntegrationSource): "success" | "warning" | "danger" | "info" | "neutral" {
  if (!s.configured) return "neutral";
  if (s.data_status === "available") return "success";
  if (s.data_status === "partial") return "warning";
  if (s.data_status === "invalid") return "danger";
  if (s.data_status === "missing") return "warning";
  return "neutral";
}
