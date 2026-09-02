import * as React from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

const base =
  "inline-flex items-center justify-center gap-2 rounded-[7px] font-medium transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] " +
  "disabled:opacity-50 disabled:pointer-events-none";

const variants: Record<Variant, string> = {
  primary: "bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)]",
  secondary:
    "bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--border)]",
  ghost: "bg-transparent text-[var(--foreground)] hover:bg-[var(--surface-raised)]",
  danger: "bg-[var(--danger)] text-white hover:opacity-90",
};

const sizes: Record<Size, string> = {
  md: "h-9 px-4 text-sm",
  sm: "h-8 px-3 text-sm",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  );
}
