import Link from "next/link";

const NAV = [
  { href: "/today", label: "Hoje" },
  { href: "/work", label: "Caixa de trabalho" },
  { href: "/pages", label: "Páginas" },
  { href: "/technical", label: "SEO Técnico" },
  { href: "/editorial", label: "Editorial" },
  { href: "/agents", label: "Agentes & Execuções" },
  { href: "/experiments", label: "Experimentos" },
  { href: "/integrations", label: "Fontes de dados" },
  { href: "/activity", label: "Histórico" },
  { href: "/settings", label: "Configurações" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-[var(--background)]">
      <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="flex h-14 items-center px-4 text-sm font-semibold">SEO Agent</div>
        <nav className="space-y-0.5 px-2">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="block rounded-md px-3 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--surface-raised)]"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-6">
          <div className="text-sm font-medium text-[var(--muted)]">Control Center</div>
          <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
            <span>unicorniohater.com.br</span>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
