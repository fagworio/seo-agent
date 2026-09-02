"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, Correction, Finding } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";

type View = "problems" | "corrections";

export default function TechnicalPage() {
  const [view, setView] = useState<View>("problems");
  const [selected, setSelected] = useState<Correction | null>(null);
  const qc = useQueryClient();

  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") });
  const csrf = me.data?.csrf_token;

  const problems = useQuery({
    queryKey: ["findings"],
    queryFn: () => api.get<{ problems: Finding[] }>("/findings?limit=200"),
  });
  const corrections = useQuery({
    queryKey: ["corrections"],
    queryFn: () => api.get<{ corrections: Correction[] }>("/actions?limit=200"),
  });

  const execute = useMutation({
    mutationFn: (fingerprint: string) => api.post<{ ok: boolean; approved: boolean; dry_run: boolean }>(`/actions/${fingerprint}/execute`, {}, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corrections"] }),
  });

  const isLoading = problems.isLoading || corrections.isLoading;
  const error = (problems.error ?? corrections.error) as ApiError | null;
  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{error.message}</div>;

  const problemsList = problems.data!.problems;
  const correctionsList = corrections.data!.corrections;
  const correctionsView = view === "corrections";

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        <Tab active={!correctionsView} onClick={() => setView("problems")}>Problemas ({problemsList.length})</Tab>
        <Tab active={correctionsView} onClick={() => setView("corrections")}>Correções disponíveis ({correctionsList.length})</Tab>
      </div>

      {!correctionsView ? (
        <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
              <tr><th className="px-3 py-2">Regra</th><th className="px-3 py-2">URL</th><th className="px-3 py-2">Severidade</th></tr>
            </thead>
            <tbody>
              {problemsList.map((f, i) => (
                <tr key={i} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2">{f.rule_id}</td>
                  <td className="max-w-md truncate px-3 py-2">{f.url}</td>
                  <td className="px-3 py-2"><SeverityBadge s={f.severity} /></td>
                </tr>
              ))}
              {problemsList.length === 0 && <tr><td colSpan={3} className="px-3 py-6 text-center text-[var(--muted)]">Nenhum problema.</td></tr>}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
              <tr><th className="px-3 py-2">Regra</th><th className="px-3 py-2">URL</th><th className="px-3 py-2">Status</th><th className="px-3 py-2"><span className="sr-only">Ação</span></th></tr>
            </thead>
            <tbody>
              {correctionsList.map((c) => (
                <tr key={c.fingerprint} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2">{c.rule_id}</td>
                  <td className="max-w-md truncate px-3 py-2">{c.url}</td>
                  <td className="px-3 py-2"><Badge tone={c.status === "executed" ? "success" : "warning"}>{c.status}</Badge></td>
                  <td className="px-3 py-2 text-right">
                    <Button size="sm" variant="secondary" onClick={() => setSelected(c)}>Preview</Button>
                  </td>
                </tr>
              ))}
              {correctionsList.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma correção registrada.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="rounded-[11px] border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold">Safe fix · {selected.rule_id}</div>
            <button className="text-[var(--muted)]" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="mb-2 text-xs text-[var(--muted)]">{selected.url}</div>

          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-md border border-[var(--border)] p-3 text-sm">
              <div className="mb-1 text-xs font-medium text-[var(--muted)]">Antes</div>
              <pre className="whitespace-pre-wrap font-mono text-xs">{JSON.stringify(selected.before ?? {}, null, 2)}</pre>
            </div>
            <div className="rounded-md border border-[var(--border)] p-3 text-sm">
              <div className="mb-1 text-xs font-medium text-[var(--muted)]">Depois</div>
              <pre className="whitespace-pre-wrap font-mono text-xs">{JSON.stringify(selected.after ?? {}, null, 2)}</pre>
            </div>
          </div>
          <div className="mb-4">
            <div className="mb-1 text-xs font-medium text-[var(--muted)]">Rollback</div>
            <pre className="whitespace-pre-wrap font-mono text-xs text-[var(--muted)]">{JSON.stringify(selected.rollback ?? {}, null, 2)}</pre>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={() => execute.mutate(selected.fingerprint)} disabled={csrf === undefined}>
              {execute.isPending ? "Aprovando…" : "Executar"}
            </Button>
            <span className="text-xs text-[var(--muted)]">Requer permissão technical.safe_fix + reautenticação.</span>
          </div>
          {execute.isSuccess && <p className="mt-2 text-sm text-[var(--success)]">Aprovado. Execução em {execute.data.dry_run ? "dry-run" : "modo real"} (worker).</p>}
          {execute.error && <p className="mt-2 text-sm text-[var(--danger)]">{(execute.error as Error).message}</p>}
        </div>
      )}
    </div>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>
      {children}
    </button>
  );
}

function SeverityBadge({ s }: { s: string }) {
  const tone = s === "critical" || s === "high" ? "danger" : s === "medium" ? "warning" : "neutral";
  return <Badge tone={tone}>{s}</Badge>;
}
