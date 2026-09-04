"use client";

import { useQuery } from "@tanstack/react-query";
import { api, Account } from "@/lib/api";
import { Card } from "@/design-system/card";
import { Badge } from "@/design-system/badge";

const ROLE_LABELS: Record<string, string> = { admin: "Administrador", operator: "Operador SEO", editor: "Editor", viewer: "Leitor" };

export default function SettingsOverview() {
  const { data: account } = useQuery({ queryKey: ["account"], queryFn: () => api.get<Account>("/account") });
  const a = account;
  return (
    <div className="max-w-2xl space-y-4">
      <Card title="Minha conta">
        <div className="text-sm">
          <p className="font-medium">{a?.name || "—"}</p>
          <p className="text-[var(--muted)]">{a?.email || ""}</p>
          <div className="mt-2 flex items-center gap-3 text-xs">
            <span>{a?.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</span>
            <Badge tone={a?.is_mfa_enabled ? "success" : "warning"}>{a?.is_mfa_enabled ? "2FA ativada" : "2FA desativada"}</Badge>
          </div>
          <p className="mt-3 text-xs text-[var(--muted)]">
            Gerencie perfil, segurança, sessões e preferências no menu à esquerda. A área de Administração
            (usuários, funções) aparece apenas para quem tem permissão.
          </p>
        </div>
      </Card>
    </div>
  );
}
