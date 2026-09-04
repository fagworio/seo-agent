import Link from "next/link";

const ACCOUNT = [
  { href: "/settings/profile", label: "Perfil" },
  { href: "/settings/security", label: "Segurança" },
  { href: "/settings/preferences", label: "Preferências" },
  { href: "/settings", label: "Visão geral" },
];
const ADMIN = [
  { href: "/settings/users", label: "Usuários" },
  { href: "/settings/roles", label: "Funções e permissões" },
  { href: "/settings/audit", label: "Auditoria de acesso" },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-8">
      <aside className="w-56 shrink-0">
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Minha conta</div>
        <nav className="mb-6 space-y-0.5">
          {ACCOUNT.map((i) => (
            <Link key={i.href} href={i.href} className="block rounded-md px-3 py-1.5 text-sm text-[var(--foreground)] hover:bg-[var(--surface-raised)]">{i.label}</Link>
          ))}
        </nav>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Administração</div>
        <nav className="space-y-0.5">
          {ADMIN.map((i) => (
            <Link key={i.href} href={i.href} className="block rounded-md px-3 py-1.5 text-sm text-[var(--foreground)] hover:bg-[var(--surface-raised)]">{i.label}</Link>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
