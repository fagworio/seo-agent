"use client";

import { useEffect, useRef } from "react";

/** Drawer acessível: fecha por Escape, prende foco e o devolve ao gatilho. */
export function Drawer({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previousFocus.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () => Array.from(panel?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    focusable()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previousFocus.current?.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onMouseDown={onClose}>
      <section
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="h-full w-full max-w-lg overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] p-6 shadow-[0_16px_40px_rgba(22,31,45,.12)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </section>
    </div>
  );
}
