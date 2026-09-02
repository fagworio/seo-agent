"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError, Experiment } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

export default function ExperimentsPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api.get<{ experiments: Experiment[] }>("/experiments?limit=100"),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const items = data!.experiments;
  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-[var(--muted)]">
        Mudança não termina em executado — termina em <strong>medido</strong>. Distinguimos{" "}
        <strong>movimento observado</strong> de certeza causal.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((exp, i) => (
          <Card key={i} title={exp.keyword || exp.url}>
            <div className="mb-3 flex items-center justify-between">
              <Badge tone={stateTone(exp.measurement_state)}>{exp.measurement_state}</Badge>
              {exp.verdict && <Badge tone={verdictTone(exp.verdict)}>{exp.verdict}</Badge>}
            </div>
            <dl className="space-y-1 text-sm">
              <Row k="Tipo" v={exp.opportunity_type} />
              <Row k="Ação" v={exp.implemented_action || "—"} />
              <Row k="Implementada" v={exp.implemented_at || "—"} />
              <Row k="URL" v={exp.url || "—"} />
              {gscPosition(exp) !== null && <Row k="Baseline GSC" v={String(gscPosition(exp))} />}
            </dl>
            <div className="mt-3 flex gap-2 text-xs text-[var(--muted)]">
              {Object.entries(exp.windows).map(([k, measured]) => (
                <span key={k} className={measured ? "text-[var(--success)]" : ""}>
                  {k}: {measured ? "medido" : "—"}
                </span>
              ))}
            </div>
          </Card>
        ))}
        {items.length === 0 && (
          <div className="text-sm text-[var(--muted)]">Nenhuma intervenção medida ainda.</div>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[var(--muted)]">{k}</dt>
      <dd className="max-w-[60%] truncate">{v}</dd>
    </div>
  );
}

function gscPosition(exp: Experiment): number | null {
  const gsc = exp.baseline?.gsc as { position?: number | null } | undefined;
  return typeof gsc?.position === "number" ? gsc.position : null;
}

function stateTone(s: string): "success" | "warning" | "info" | "neutral" {
  if (s === "measured") return "success";
  if (s === "measuring") return "info";
  return "warning";
}

function verdictTone(v: string): "success" | "warning" | "danger" | "neutral" {
  if (v === "improved") return "success";
  if (v === "worsened") return "danger";
  if (v === "neutral") return "neutral";
  return "warning";
}
