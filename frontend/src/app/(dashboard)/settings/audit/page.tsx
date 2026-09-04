"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ActivityEntry } from "@/lib/api";
import { Card } from "@/design-system/card";
import { Badge } from "@/design-system/badge";

const EVENT_LABELS: Record<string, string> = {
  LOGIN_SUCCESS: "Login", LOGIN_FAILURE: "Falha de login", LOGOUT: "Logout",
  MFA_SUCCESS: "MFA ok", MFA_FAILURE: "Falha de MFA", MFA_ENABLED: "MFA ativada", MFA_DISABLED: "MFA desativada",
  PASSWORD_CHANGED: "Senha alterada", PASSWORD_RESET_REQUESTED: "Reset solicitado", PASSWORD_RESET_FORCED: "Reset forçado",
  USER_CREATED: "Usuário criado", USER_ENABLED: "Usuário ativado", USER_DISABLED: "Usuário desativado",
  ROLE_CHANGED: "Função alterada", SESSION_REVOKED: "Sessão encerrada", ALL_SESSIONS_REVOKED: "Todas as sessões encerradas",
  PROFILE_UPDATED: "Perfil atualizado", PROFILE_EMAIL_CHANGED: "Email alterado",
};

function typeTone(type: string): "danger" | "warning" | "success" | "info" | "neutral" {
  if (type === "auth") return "warning";
  if (type === "agent_run") return "info";
  if (type === "audit") return "neutral";
  return "neutral";
}

export default function AuditPage() {
  const [filter, setFilter] = useState<"all" | "auth" | "agent_run" | "audit">("all");
  const { data } = useQuery({ queryKey: ["activity"], queryFn: () => api.get<{ activity: ActivityEntry[] }>("/activity?limit=200") });
  const entries = (data?.activity ?? []).filter((e) => filter === "all" || e.type === filter);

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex gap-1">
        {(["all", "auth", "agent_run", "audit"] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={`rounded-md px-3 py-1.5 text-sm ${filter === f ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>
            {f === "all" ? "Todos" : f === "auth" ? "Acesso" : f === "agent_run" ? "Agentes" : "Auditoria"}
          </button>
        ))}
      </div>
      <Card title="Auditoria de acesso">
        <ol className="space-y-3">
          {entries.map((e, i) => (
            <li key={i} className="flex items-start gap-3 border-b border-[var(--border)] pb-2 text-sm">
              <span className="w-36 shrink-0 text-xs text-[var(--muted)]">{new Date(e.ts).toLocaleString("pt-BR")}</span>
              <Badge tone={typeTone(e.type)}>{e.type}</Badge>
              <span className="w-40 shrink-0 text-xs">{e.actor}</span>
              <span className="min-w-0 flex-1 truncate">{EVENT_LABELS[e.event] ?? e.event}</span>
              <span className="font-mono text-[10px] text-[var(--muted)]">{e.event}</span>
            </li>
          ))}
          {entries.length === 0 && <li className="text-sm text-[var(--muted)]">Sem eventos.</li>}
        </ol>
      </Card>
    </div>
  );
}
