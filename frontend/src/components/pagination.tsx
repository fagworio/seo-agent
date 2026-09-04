"use client";

import { Button } from "@/design-system/button";

type PaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  label?: string;
  compact?: boolean;
};

/** Compact, accessible pagination for operational tables. */
export function Pagination({ page, pageSize, total, onPageChange, label = "itens", compact = false }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] px-3 py-3 text-xs text-[var(--muted)]">
      <span aria-live="polite">{first}–{last} de {total} {label}</span>
      <div className={`flex max-w-full flex-wrap items-center gap-2 ${compact ? "w-full justify-between" : ""}`}>
        <Button size="sm" variant="secondary" aria-label="Página anterior" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>{compact ? "‹" : "Anterior"}</Button>
        <span className="min-w-16 text-center tabular-nums">Página {page} de {pageCount}</span>
        <Button size="sm" variant="secondary" aria-label="Próxima página" onClick={() => onPageChange(page + 1)} disabled={page >= pageCount}>{compact ? "›" : "Próxima"}</Button>
      </div>
    </div>
  );
}

export function pageSlice<T>(items: T[], page: number, pageSize: number) {
  return items.slice((page - 1) * pageSize, page * pageSize);
}
