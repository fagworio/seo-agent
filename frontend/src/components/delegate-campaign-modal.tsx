"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Drawer } from "@/design-system/drawer";
import { Input } from "@/design-system/input";

type Preview = {
  eligible: { fingerprint: string; rule_id: string; url: string; risk: string; reversible: boolean }[];
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
};

export function DelegateCampaignModal({ fingerprints, onClose, onCreated }: {
  fingerprints: string[];
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("Atualização de títulos");
  const [mode, setMode] = useState<"now" | "delegated">("delegated");
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
      fingerprints,
      execution_mode: mode,
    }, me.data?.csrf_token),
    onSuccess: (campaign) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      onCreated(campaign.id);
    },
  });

  const p = preview.data;
  const typeLabel = p?.action_type ? (RULE_LABELS[p.action_type] ?? p.action_type) : "—";

  return (
    <Drawer title="Delegar melhorias" onClose={onClose}>
      {preview.isLoading && <p className="text-sm text-[var(--muted)]">Validando seleção…</p>}
      {preview.isError && <p className="text-sm text-[var(--danger)]">{(preview.error as Error).message}</p>}

      {p && (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <SummaryRow label="Tipo" value={typeLabel} />
            <SummaryRow label="Selecionadas" value={String(fingerprints.length)} />
            <SummaryRow label="Elegíveis" value={String(p.eligible.length)} />
            <SummaryRow label="Exigem revisão" value={String(p.incompatible.length + p.missing.length)} />
            <SummaryRow label="Risco" value={p.action_type === "image_no_alt" ? "Baixo" : "Baixo (reversível)"} />
            <SummaryRow label="Reversível" value="Sim" />
            <SummaryRow label="Limite" value={`${p.max_actions_per_run} por ciclo`} />
          </div>

          {!p.homogeneous && (
            <div className="rounded-md border border-[var(--danger)] p-3 text-xs text-[var(--danger)]">
              A seleção mistura tipos diferentes (títulos, canonical, links…). Campanhas exigem itens homogêneos.
            </div>
          )}
          {p.incompatible.length > 0 && (
            <p className="text-xs text-[var(--warning)]">{p.incompatible.length} item(ns) sem fix suportado serão deixados de fora.</p>
          )}
          {p.missing.length > 0 && (
            <p className="text-xs text-[var(--warning)]">{p.missing.length} fingerprint(s) não encontradas.</p>
          )}

          <div>
            <label className="mb-1 block font-medium">Nome da campanha</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div>
            <div className="mb-1 font-medium">Execução</div>
            <div className="flex gap-4">
              <label className="flex items-center gap-1"><input type="radio" checked={mode === "now"} onChange={() => setMode("now")} /> Executar agora</label>
              <label className="flex items-center gap-1"><input type="radio" checked={mode === "delegated"} onChange={() => setMode("delegated")} /> Delegar ao Hermes</label>
            </div>
            <p className="mt-1 text-xs text-[var(--muted)]">
              O Hermes processa até {p.max_actions_per_run} por ciclo, verifica cada uma e continua nos próximos ciclos até terminar.
            </p>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>Cancelar</Button>
            <Button size="sm" onClick={() => create.mutate()}
              disabled={!p.homogeneous || p.eligible.length === 0 || create.isPending}>
              {create.isPending ? "Criando…" : "Criar campanha"}
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
      <div className="tabular-nums">{value}</div>
    </div>
  );
}
