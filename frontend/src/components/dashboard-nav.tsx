"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function DashboardNav({ items }: { items: { href: string; label: string }[] }) {
  const pathname = usePathname();
  return <nav className="space-y-0.5 px-2" aria-label="Navegação principal">
    {items.map((item) => {
      const active = pathname === item.href || (item.href !== "/today" && pathname.startsWith(`${item.href}/`));
      return <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}
        className={`block rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] ${active ? "bg-[var(--primary-soft)] font-medium text-[var(--primary)]" : "text-[var(--foreground)] hover:bg-[var(--surface-raised)]"}`}>
        {item.label}
      </Link>;
    })}
  </nav>;
}
