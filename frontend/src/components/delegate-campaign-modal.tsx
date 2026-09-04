"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { Input } from "@/design-system/input";

type EligibleItem = {
  fingerprint: string;
  rule_id: string;
  url: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  risk: string;
  reversible: boolean;
};

type Preview = {
  eligible: EligibleItem[];
  incompatible: { fingerprint: string; reason: string }[];
  missing: string[];
  action_type: string | null;
  homogeneous: boolean;
  per_cycle: number;
  max_actions_per_run: number;
};

const RULE_LABELS: Record<string, string> = {
  title_manual: "Atualização de títulos",
  title_opportunity: "Atualização de títulos",
  image_no_alt: "Texto alternativo (alt)",
  internal_link: "Links internos",
  interlink: "Links internos",
};

export function DelegateCampaignModal({ fingerprints, onClose, onCreated }: {
  fingerprints: string[];
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("Atualização de títulos");
  const [mode, setMode] = useState<"now" | "delegated">("delegated");
  const [limit, setLimit] = useState(10);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") });

  const preview = useQuery({
    queryKey: ["campaign-preview", [...fingerprints].sort()],
    queryFn: () => api.post<Preview>("/campaigns/preview", { fingerprints }, me.data?.csrf_token),
    enabled: fingerprints.length > 0 && !!me.data?.csrf_token,
  });

  const create = useMutation({
    mutationFn: () => api.post<{ id: number }>("/campaigns", {
      name,
      action_type: preview.data?.action_type,
      fingerprints: effectiveFingerprints,
      execution_mode: mode,
      max_actions_per_run: limit,
    }, me.data?.csrf_token),
    onSuccess: async (campaign) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      if (mode === "now") {
        // "Executar agora" acorda o MESMO runner (POST /campaigns/{id}/run).
        await api.post(`/campaigns/${campaign.id}/run`, {}, me.data?.csrf_token).catch(() => undefined);
      }
      onCreated(campaign.id);
    },
  });

  const p = preview.data;
  const effectiveFingerprints = useMemo(
    () => fingerprints.filter((fp) => !excluded.has(fp)),
    [fingerprints, excluded],
  );
  const visible = (p?.eligible ?? []).filter((it) => !excluded.has(it.fingerprint));
  const typeLabel = p?.action_type ? (RULE_LABELS[p.action_type] ?? p.action_type) : "—";

  return (
    <Drawer title="Delegar melhorias" onClose={onClose}>
      {preview.isLoading && <p className="text-sm text-[var(--muted)]">Validando seleção…</p>}
      {preview.isError && <p className="text-sm text-[var(--danger)]">{(preview.error as Error).message}</p>}

      {p && (
        <div className="space-y-4 text-sm">
          {/* Resumo do lote */}
          <div className="flex items-baseline justify-between">
            <div className="text-base font-semibold">{typeLabel}</div>
            <Badge tone={p.homogeneous ? "success" : "danger"}>{p.homogeneous ? "homogêneo" : "tipos mistos"}</Badge>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <SummaryRow label="Selecionadas" value={String(fingerprints.length)} />
            <SummaryRow label="Automatizáveis" value={String(visible.length)} />
            <SummaryRow label="Revisão manual" value={String(p.incompatible.length + p.missing.length)} />
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted)]">
            <span>Risco: <strong className="text-[var(--foreground)]">{riskLabel(p.action_type)}</strong></span>
            <span>Reversível: <strong className="text-[var(--foreground)]">Sim</strong></span>
            <span>Limite por ciclo: <strong className="text-[var(--foreground)]">{limit}</strong></span>
            <span>Dados GSC: <strong className="text-[var(--foreground)]">{visible.length}</strong></span>
          </div>

          {/* Alertas */}
          {!p.homogeneous && (
            <Alert tone="danger">A seleção mistura tipos diferentes. Crie campanhas separadas para títulos, links, ALT…</Alert>
          )}
          {(p.incompatible.length > 0 || p.missing.length > 0) && (
            <Alert tone="warning">
              {p.incompatible.length + p.missing.length} item(ns) não serão executados
              {p.incompatible.length > 0 && ` (${p.incompatible.length} sem fix suportado / stale)`}
              {p.missing.length > 0 && ` (${p.missing.length} não encontrados)`}.
            </Alert>
          )}

          {/* Preview before/after com remover */}
          {visible.length > 0 && (
            <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
              <div className="text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Alterações ({visible.length})</div>
              {visible.map((it) => (
                <div key={it.fingerprint} className="rounded-md border border-[var(--border)] p-3">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-[var(--muted)]">{shortUrl(it.url)}</span>
                    <Button variant="ghost" size="sm" onClick={() => setExcluded((s) => new Set(s).add(it.fingerprint))}>Remover</Button>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded bg-[var(--surface-raised)] p-2">
                      <div className="text-[10px] uppercase text-[var(--muted)]">Antes</div>
                      <div className="line-clamp-2">{fieldValue(it.before) || "—"}</div>
                    </div>
                    <div className="rounded bg-[var(--surface-raised)] p-2">
                      <div className="text-[10px] uppercase text-[var(--muted)]">Depois</div>
                      <div className="line-clamp-2">{fieldValue(it.after) || "—"}</div>
                    </div>
                  </div>
                  <div className="mt-1 text-[11px] text-[var(--muted)]">
                    Risco {riskLabel(it.rule_id)} · {it.reversible ? "Reversível" : "Não reversível"}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Configuração de delegação */}
          <div className="space-y-3 border-t border-[var(--border)] pt-3">
            <div>
              <label className="mb-1 block font-medium">Nome da campanha</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <div className="mb-1 font-medium">Como executar</div>
              <div className="flex gap-4">
                <label className="flex items-center gap-1"><input type="radio" checked={mode === "now"} onChange={() => setMode("now")} /> Executar agora</label>
                <label className="flex items-center gap-1"><input type="radio" checked={mode === "delegated"} onChange={() => setMode("delegated")} /> Delegar ao Hermes</label>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <label className="font-medium">Limite por ciclo</label>
              <input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
                className="h-9 w-20 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-2 text-sm" />
              <span className="text-xs text-[var(--muted)]">alterações</span>
            </div>
            <p className="text-xs text-[var(--muted)]">
              {mode === "now"
                ? "Inicia uma execução do agente agora; até o limite por ciclo será processado nesta rodada e o restante fica pendente."
                : "O Hermes processa automaticamente em ciclos, verificando cada alteração e continuando até terminar."}
            </p>

            {/* Confirmação (autorização de escrita) */}
            <label className="flex items-start gap-2 text-xs text-[var(--muted)]">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5" />
              <span>Autorizo o Hermes a alterar {visible.length} item(ns) no WordPress. Todas as alterações têm histórico e rollback.</span>
            </label>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>Cancelar</Button>
            <Button size="sm" onClick={() => create.mutate()}
              disabled={!p.homogeneous || visible.length === 0 || !confirmed || create.isPending}>
              {create.isPending ? "Criando…" : mode === "now" ? "Iniciar execução" : "Criar campanha"}
            </Button>
          </div>
          {create.isError && <p className="text-sm text-[var(--danger)]">{(create.error as Error).message}</p>}
        </div>
      )}
    </Drawer>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--border)] p-2">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Alert({ tone, children }: { tone: "danger" | "warning"; children: React.ReactNode }) {
  return (
    <div className={`rounded-md border border-[var(--${tone})] bg-[var(--surface-raised)] p-3 text-xs`} style={{ color: `var(--${tone})` }}>
      {children}
    </div>
  );
}

function fieldValue(rec: Record<string, unknown> | null | undefined): string {
  if (!rec) return "";
  const v = Object.values(rec)[0];
  return v == null ? "" : String(v);
}

function riskLabel(ruleId: string | null | undefined): string {
  if (!ruleId) return "—";
  if (["title_manual", "title_opportunity", "image_no_alt"].includes(ruleId)) return "baixo";
  if (["internal_link", "interlink"].includes(ruleId)) return "revisão manual";
  return "revisão manual";
}

function shortUrl(u: string): string {
  const path = u.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const parts = path.split("/");
  return parts.length > 1 ? `/${parts.slice(1).join("/")}` : u;
}
