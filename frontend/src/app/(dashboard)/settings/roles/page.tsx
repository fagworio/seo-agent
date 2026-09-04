"use client";

import { useQuery } from "@tanstack/react-query";
import { api, Role } from "@/lib/api";
import { Card } from "@/design-system/card";
import { Badge } from "@/design-system/badge";

const ROLE_LABELS: Record<string, string> = { admin: "Administrador", operator: "Operador SEO", editor: "Editor", viewer: "Leitor" };

// Apresentação amigável de permissões (agrupadas por domínio). Nunca mostrar
// apenas o código (ex.: "editorial.review") como interface principal.
const PERM_PRESENTATION: [string, string][] = [
  ["dashboard.read", "Painel — consultar"],
  ["pages.read", "Páginas — consultar"],
  ["opportunity.read", "Oportunidades — consultar"],
  ["opportunity.review", "Oportunidades — aprovar/rejeitar"],
  ["technical.read", "SEO técnico — consultar"],
  ["technical.safe_fix", "SEO técnico — executar correções"],
  ["technical.approve_risky", "SEO técnico — aprovar correções de risco"],
  ["editorial.read", "Editorial — consultar"],
  ["editorial.review", "Editorial — revisar"],
  ["editorial.publish_confirm", "Editorial — confirmar publicação"],
  ["agent.read", "Agentes — consultar"],
  ["agent.run", "Agentes — executar"],
  ["agent.cancel", "Agentes — cancelar"],
  ["experiment.read", "Experimentos — consultar"],
  ["integration.read", "Integrações — consultar"],
  ["integration.manage", "Integrações — gerenciar"],
  ["users.read", "Usuários — consultar"],
  ["users.manage", "Usuários — gerenciar"],
  ["settings.read", "Configurações — consultar"],
  ["settings.manage", "Configurações — gerenciar"],
  ["audit.read", "Auditoria — consultar"],
];

const GROUP: Record<string, string> = { dashboard: "Painel", pages: "Páginas", opportunity: "Oportunidades", technical: "SEO técnico", editorial: "Editorial", agent: "Agentes", experiment: "Experimentos", integration: "Integrações", users: "Usuários", settings: "Configurações", audit: "Auditoria" };

function permLabel(perm: string) {
  return PERM_PRESENTATION.find(([p]) => p === perm)?.[1] ?? perm;
}
function permGroup(perm: string) {
  return GROUP[perm.split(".")[0]] ?? perm.split(".")[0];
}

export default function RolesPage() {
  const { data } = useQuery({ queryKey: ["roles"], queryFn: () => api.get<{ roles: Role[] }>("/roles") });
  const roles = data?.roles ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-sm text-[var(--muted)]">Funções definem o acesso de cada usuário. Cada função é um conjunto de permissões (deny-by-default).</p>
      {roles.map((role) => {
        const groups = Array.from(new Set(role.permissions.map(permGroup))).sort();
        return (
          <Card key={role.name} title={ROLE_LABELS[role.name] ?? role.name}>
            <p className="mb-3 text-sm text-[var(--muted)]">{role.description}</p>
            <div className="grid gap-4 md:grid-cols-2">
              {groups.map((g) => (
                <div key={g}>
                  <div className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">{g}</div>
                  <ul className="space-y-0.5 text-sm">
                    {role.permissions.filter((p) => permGroup(p) === g).map((p) => (
                      <li key={p} className="flex items-center gap-1"><span className="text-[var(--success)]">✓</span><span>{permLabel(p)}</span><span className="ml-auto text-[10px] text-[var(--muted)]">{p}</span></li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <div className="mt-3"><Badge tone="primary">{role.permissions.length} permissões</Badge></div>
          </Card>
        );
      })}
    </div>
  );
}
