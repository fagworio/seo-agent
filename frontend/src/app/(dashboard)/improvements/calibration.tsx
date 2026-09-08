"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { ScoreBar } from "@/features/intelligence";

type Calibration = { report: { bands: Record<string, { n: number; improved: number; not_improved: number; improved_rate: number | null; samples: number }>; gradient: number | null; n_outcomes: number }; adjusted_opportunity_weights: Record<string, number> };
const BAND_ORDER = ["80-100", "60-80", "40-60", "<40"];
const WEIGHT_LABEL: Record<string, string> = { rankability: "Rankability", demand: "Demanda", headroom: "Headroom", momentum: "Momentum", strategic_fit: "Ajuste estratégico" };

export function Calibration() {
  const q = useQuery({ queryKey: ["calibration"], queryFn: () => api.get<Calibration>("/calibration") });
  if (q.isLoading) return <p className="text-sm text-[var(--muted)]">Carregando calibração…</p>;
  if (q.error) return <p className="text-sm text-[var(--danger)]">{(q.error as ApiError).message}</p>;
  const { report, adjusted_opportunity_weights } = q.data ?? { report: { bands: {}, gradient: null, n_outcomes: 0 }, adjusted_opportunity_weights: {} };
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-3">
        <h3 className="font-medium">Melhoria observada por faixa de score (R9)</h3>
        <p className="text-sm text-[var(--muted)]">Quanto maior a faixa, maior a taxa de melhoria real medidada — é o que a calibração usa para ajustar os pesos. Até haver medições suficientes, os pesos ficam no default.</p>
        <div className="space-y-2">
          {BAND_ORDER.map((b) => { const band = report.bands?.[b]; if (!band) return null; return (
            <div key={b} className="rounded-md border border-[var(--border)] p-3 text-sm">
              <div className="flex items-center justify-between"><strong>{b}</strong><Badge tone={band.improved_rate != null && band.improved_rate >= 0.5 ? "success" : "warning"}>{band.improved_rate != null ? `${Math.round(band.improved_rate * 100)}% melhoraram` : "sem evidência"}</Badge></div>
              <ScoreBar label={`${band.samples} amostras`} score={band.improved_rate != null ? band.improved_rate * 100 : null} />
            </div>); })}
          {Object.keys(report.bands ?? {}).length === 0 && <p className="text-sm text-[var(--muted)]">Nenhum outcome medido ainda.</p>}
        </div>
      </section>
      <section className="space-y-3">
        <h3 className="font-medium">Pesos ajustados do Opportunity Engine</h3>
        <div className="space-y-1.5">{Object.entries(adjusted_opportunity_weights).map(([k, v]) => <ScoreBar key={k} label={WEIGHT_LABEL[k] ?? k} score={v * 100} />)}</div>
        <p className="text-xs text-[var(--muted)]">Gradiente: {report.gradient != null ? `${report.gradient > 0 ? "+" : ""}${report.gradient}` : "sem evidência"} · {report.n_outcomes} outcomes analisados. Sem Gradiente = pesos default.</p>
      </section>
    </div>
  );
}
