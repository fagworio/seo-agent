import * as React from "react";

export function Card({
  className = "",
  title,
  children,
}: {
  className?: string;
  title?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}
    >
      {title && <div className="mb-3 text-sm font-semibold">{title}</div>}
      <div>{children}</div>
    </div>
  );
}
