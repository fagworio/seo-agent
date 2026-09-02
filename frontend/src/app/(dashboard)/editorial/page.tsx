"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError, Opportunity } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

const COLUMNS = ["proposed", "approved", "published", "measured"] as const;

export default function EditorialPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["editorial", "backlog"],
    queryFn: () => api.get<{ work_items: Opportunity[] }>("/work-items?source=backlog&limit=200"),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  const items = data!.work_items;
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
      {COLUMNS.map((col) => {
        const colItems = items.filter((i) => i.status === col);
        return (
          <Card key={col} title={`${col} (${colItems.length})`}>
            <ul className="space-y-2">
              {colItems.map((item) => (
                <li key={item.id} className="rounded-md border border-[var(--border)] p-2 text-sm">
                  <div className="truncate font-medium">{item.title || item.id}</div>
                  <div className="mt-1 flex items-center justify-between text-xs text-[var(--muted)]">
                    <span>{item.type}</span>
                    <span className="tabular-nums">{String(item.score ?? "—")}</span>
                  </div>
                </li>
              ))}
              {colItems.length === 0 && <li className="text-sm text-[var(--muted)]">Vazio.</li>}
            </ul>
          </Card>
        );
      })}
      {items.length === 0 && <div className="text-sm text-[var(--muted)]">Nenhuma pauta no backlog.</div>}
    </div>
  );
}
