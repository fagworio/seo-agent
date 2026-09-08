"use client";

// Logica de nivel/cores de um score (0-100) — nao recalcula o score, so apresenta.
export type ScoreLevel = "muito_baixo" | "baixo" | "moderado" | "alto" | "muito_alto";

export function classify(score: number | null | undefined): { level: ScoreLevel; label: string; tone: "danger" | "warning" | "info" | "success" } {
  const s = typeof score === "number" && isFinite(score) ? score : null;
  if (s === null) return { level: "moderado", label: "—", tone: "info" };
  if (s < 30) return { level: "muito_baixo", label: "Muito baixo", tone: "danger" };
  if (s < 50) return { level: "baixo", label: "Baixo", tone: "warning" };
  if (s < 70) return { level: "moderado", label: "Moderado", tone: "info" };
  if (s < 85) return { level: "alto", label: "Alto", tone: "success" };
  return { level: "muito_alto", label: "Muito alto", tone: "success" };
}

export type Factor = { key?: string; label: string; value: number | null; weight?: number; contribution?: number; explanation?: string };
export interface IntelligenceScore {
  score?: number;
  label?: string;
  level?: ScoreLevel | string;
  factors?: Factor[];
  confidence?: { score?: number; label?: string };
  status?: string;              // blocked | partial | available
  limitations?: string[];
  evidence?: { source: string; window?: string; status?: string }[];
}
