import { ThemeToggle } from "@/components/theme-toggle";
import { DashboardNav } from "@/components/dashboard-nav";

const NAV = [
  { href: "/today", label: "Hoje" },
  { href: "/work", label: "Caixa de trabalho" },
  { href: "/pages", label: "Páginas" },
  { href: "/technical", label: "SEO Técnico" },
  { href: "/editorial", label: "Editorial" },
  { href: "/improvements", label: "Melhorias" },
  { href: "/agents", label: "Agentes & Execuções" },
  { href: "/experiments", label: "Experimentos" },
  { href: "/integrations", label: "Fontes de dados" },
  { href: "/activity", label: "Histórico" },
  { href: "/settings", label: "Configurações" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-[var(--background)]">
      <aside className="hidden w-56 shrink-0 border-r border-[var(--border)] bg-[var(--surface)] md:block">
        <div className="flex h-14 items-center px-4 text-sm font-semibold">SEO Agent</div>
        <DashboardNav items={NAV} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-6">
          <div className="text-sm font-medium text-[var(--muted)]">Central de operações</div>
          <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
            <span>unicorniohater.com.br</span>
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
