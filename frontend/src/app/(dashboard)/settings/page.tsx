import { Card } from "@/design-system/card";

const GROUPS = [
  { title: "Conta & Segurança", items: ["Perfil", "Senha", "MFA", "Sessões ativas"] },
  { title: "Agentes & Agendamentos", items: ["Agentes", "Schedules", "Modo de execução"] },
  { title: "Integrações", items: ["WordPress", "GSC", "GA4", "CrUX", "Fontes externas"] },
  { title: "Comportamento SEO", items: ["Segurança de escrita", "Blast radius", "Aprovações"] },
  { title: "Preferências de UI", items: ["Tema (dark/light)", "Densidade", "Idioma"] },
];

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-[var(--muted)]">
        Configurações do control plane. Segredos críticos (credenciais de WordPress,
        Google, banco) permanecem em infraestrutura/secret storage — não são
        expostos em formulário web.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {GROUPS.map((group) => (
          <Card key={group.title} title={group.title}>
            <ul className="space-y-1">
              {group.items.map((item) => (
                <li key={item} className="flex items-center justify-between text-sm">
                  <span>{item}</span>
                  <span className="text-xs text-[var(--muted)]">a configurar</span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}
