"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ActivityEntry, ApiError } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Card } from "@/design-system/card";

export default function ActivityPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["activity"],
    queryFn: () => api.get<{ activity: ActivityEntry[] }>("/activity?limit=100"),
  });

  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;

  return (
    <Card title="Auditoria">
      <ol className="space-y-3">
        {data!.activity.map((entry, i) => (
          <li key={i} className="flex items-start gap-3 border-b border-[var(--border)] pb-2">
            <span className="w-40 shrink-0 font-mono text-xs text-[var(--muted)]">{entry.ts}</span>
            <span className="w-40 shrink-0 text-sm">{entry.actor}</span>
            <Badge tone={typeTone(entry.type)}>{entry.type}</Badge>
            <span className="min-w-0 flex-1 truncate text-sm">{entry.summary}</span>
          </li>
        ))}
        {data!.activity.length === 0 && <li className="text-sm text-[var(--muted)]">Sem atividade.</li>}
      </ol>
    </Card>
  );
}

function typeTone(type: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (type === "agent_run") return "info";
  if (type === "auth") return "warning";
  if (type === "audit") return "neutral";
  return "neutral";
}
