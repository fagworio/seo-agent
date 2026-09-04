"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RunDetail } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { Badge } from "@/design-system/badge";

const SOURCES = [
  { key: "wordpress", label: "WordPress" },
  { key: "sitemap", label: "Sitemap" },
  { key: "gsc", label: "Google Search Console" },
  { key: "ga4", label: "Google Analytics (GA4)" },
  { key: "crux", label: "CrUX (Core Web Vitals)" },
  { key: "corpus", label: "Corpus editorial" },
] as const;

const TERMINAL = new Set(["success", "partial", "failed", "cancelled"]);

export function RefreshDataButton() {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>(SOURCES.map((s) => s.key));
  const [runId, setRunId] = useState<number | null>(null);
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const canRun = me.data?.user.permissions.includes("agent.run") ?? false;

  const create = useMutation({
    mutationFn: () => api.post<{ id: number; status: string }>("/runs", { intent: "refresh_data", mode: "analyze", sources: selected }, me.data?.csrf_token),
    onSuccess: (run) => { setRunId(run.id); qc.invalidateQueries({ queryKey: ["runs"] }); },
  });

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.get<RunDetail>(`/runs/${runId}`),
    enabled: runId != null,
    refetchInterval: (q) => (q.state.data && !TERMINAL.has(q.state.data.status) ? 2000 : false),
  });

  const toggle = (key: string) => setSelected((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));

  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>↻ Atualizar dados</Button>
      {open && (
        <Drawer title="Atualizar dados" onClose={() => setOpen(false)}>
          {!runId || create.isPending ? (
            <>
              <p className="mb-3 text-sm text-[var(--muted)]">Escolha as fontes a atualizar. Isso gera uma execução do agente (AgentRun refresh_data) — nada é escrito no site.</p>
              <div className="mb-3 grid gap-2">
                {SOURCES.map((s) => (
                  <label key={s.key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={selected.includes(s.key)} onChange={() => toggle(s.key)} />
                    {s.label}
                  </label>
                ))}
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancelar</Button>
                <Button size="sm" onClick={() => create.mutate()} disabled={!canRun || create.isPending || selected.length === 0}>
                  {create.isPending ? "Solicitando…" : "Atualizar dados"}
                </Button>
              </div>
              {!canRun && <p className="mt-2 text-xs text-[var(--muted)]">Requer a permissão agent.run.</p>}
              {create.isError && <p className="mt-2 text-xs text-[var(--danger)]">{(create.error as Error).message}</p>}
            </>
          ) : (
            <RunProgress run={run.data} />
          )}
        </Drawer>
      )}
    </>
  );
}

function RunProgress({ run }: { run: RunDetail | undefined }) {
  if (!run) return <p className="text-sm text-[var(--muted)]">Aguardando a execução…</p>;
  const active = !TERMINAL.has(run.status);
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <Badge tone={run.status === "success" ? "success" : run.status === "partial" || run.status === "failed" ? "danger" : "info"}>
          {run.status === "queued" ? "Na fila" : run.status === "running" ? "Executando" : run.status}
        </Badge>
        <span className="text-xs text-[var(--muted)]">execução #{run.id}</span>
      </div>
      <ul className="space-y-1">
        {(run.steps ?? []).map((s) => (
          <li key={s.stage} className="flex items-center gap-2">
            <span className="text-xs text-[var(--muted)]">●</span>
            <span className="flex-1">{s.stage}</span>
            <span className="text-xs text-[var(--muted)]">{s.status}</span>
          </li>
        ))}
        {!run.steps?.length && <li className="text-xs text-[var(--muted)]">{active ? "Aguardando o worker iniciar a coleta…" : "Sem estágios registrados."}</li>}
      </ul>
      {run.summary && (
        <div className="rounded-md border border-[var(--border)] p-3 text-xs">
          <div className="mb-1 font-medium">Resultado</div>
          <pre className="whitespace-pre-wrap font-mono">{JSON.stringify(run.summary, null, 2)}</pre>
        </div>
      )}
      {run.error && <p className="text-xs text-[var(--danger)]">{run.error}</p>}
    </div>
  );
}
