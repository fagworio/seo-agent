"use client";

import { Badge } from "@/design-system/badge";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "primary";

/**
 * Estados visuais padronizados (spec UI §item 5). Um único mapa para status de
 * campanha e de item, garantindo rótulo + tom consistentes em toda a UI.
 * Nunca só cor: sempre texto (ADR-0006 §9).
 */
const META: Record<string, { label: string; tone: Tone }> = {
  // — estados de campanha —
  draft: { label: "Novo", tone: "neutral" },
  review_required: { label: "Revisão", tone: "warning" },
  approved: { label: "Aprovado", tone: "success" },
  queued: { label: "Delegado", tone: "info" },
  running: { label: "Em execução", tone: "info" },
  partial: { label: "Parcial", tone: "warning" },
  completed: { label: "Implementado", tone: "success" },
  measuring: { label: "Aguardando dados", tone: "info" },
  measured: { label: "Medido", tone: "success" },
  paused: { label: "Pausado", tone: "neutral" },
  cancelled: { label: "Cancelado", tone: "neutral" },
  failed: { label: "Falhou", tone: "danger" },
  // — estados de item —
  pending: { label: "Aguardando", tone: "info" },
  new: { label: "Novo", tone: "neutral" },
  executed: { label: "Implementado", tone: "success" },
  verified: { label: "Verificado", tone: "success" },
  stale: { label: "Precisa revisão", tone: "warning" },
  skipped: { label: "Ignorado", tone: "neutral" },
  // — execução de agente (runs) —
  success: { label: "Concluído", tone: "success" },
};

export function statusMeta(status: string | null | undefined): { label: string; tone: Tone } {
  if (!status) return { label: "—", tone: "neutral" };
  return META[status] ?? { label: status, tone: "neutral" };
}

export function StatusBadge({ status, className = "" }: { status: string | null | undefined; className?: string }) {
  const meta = statusMeta(status);
  return <Badge tone={meta.tone} className={className}>{meta.label}</Badge>;
}
