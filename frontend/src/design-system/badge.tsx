import * as React from "react";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "primary";

const tones: Record<Tone, string> = {
  neutral: "bg-[var(--surface-raised)] text-[var(--muted)] border border-[var(--border)]",
  success: "bg-[var(--success)]/10 text-[var(--success)] border border-[var(--success)]/20",
  warning: "bg-[var(--warning)]/10 text-[var(--warning)] border border-[var(--warning)]/20",
  danger: "bg-[var(--danger)]/10 text-[var(--danger)] border border-[var(--danger)]/20",
  info: "bg-[var(--info)]/10 text-[var(--info)] border border-[var(--info)]/20",
  primary: "bg-[var(--primary-soft)] text-[var(--primary)] border border-[var(--primary)]/20",
};

/** Status nunca só por cor: sempre par de texto/ícone (ADR-0006 §9). */
export function Badge({
  tone = "neutral",
  className = "",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}
      {...props}
    />
  );
}
