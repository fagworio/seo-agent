"use client";

import { useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import { Button } from "@/design-system/button";

export type DashboardWidget = {
  id: string;
  label: string;
  content: ReactNode;
  className?: string;
};

type WidgetPreferences = { order: string[]; hidden: string[] };
type DropTarget = { id: string; position: "before" | "after" };

const STORAGE_KEY = "seo-agent-today-widgets-v1";

export function DashboardWidgetLayout({ widgets }: { widgets: DashboardWidget[] }) {
  const ids = useMemo(() => widgets.map((widget) => widget.id), [widgets]);
  const [preferences, setPreferences] = useState<WidgetPreferences>({ order: ids, hidden: [] });
  const [customizing, setCustomizing] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  useEffect(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<WidgetPreferences>;
      const valid = (values: unknown) => Array.isArray(values) ? values.filter((value): value is string => typeof value === "string" && ids.includes(value)) : [];
      const order = valid(parsed.order);
      setPreferences({ order: [...order, ...ids.filter((id) => !order.includes(id))], hidden: valid(parsed.hidden) });
    } catch {
      setPreferences({ order: ids, hidden: [] });
    }
  }, [ids]);

  const ordered = useMemo(() => {
    const byId = new Map(widgets.map((widget) => [widget.id, widget]));
    return preferences.order.map((id) => byId.get(id)).filter((widget): widget is DashboardWidget => Boolean(widget));
  }, [preferences.order, widgets]);
  const visible = ordered.filter((widget) => !preferences.hidden.includes(widget.id));
  const hidden = ordered.filter((widget) => preferences.hidden.includes(widget.id));

  function persist(next: WidgetPreferences) {
    setPreferences(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }
  function move(id: string, target: string, position: DropTarget["position"] = "before") {
    if (id === target) return;
    const order = preferences.order.filter((item) => item !== id);
    const targetIndex = order.indexOf(target);
    const index = targetIndex < 0 ? order.length : targetIndex + (position === "after" ? 1 : 0);
    order.splice(index, 0, id);
    persist({ ...preferences, order });
  }
  function moveBy(id: string, offset: number) {
    const index = preferences.order.indexOf(id);
    const target = preferences.order[index + offset];
    if (target) move(id, target, offset > 0 ? "after" : "before");
  }
  function hide(id: string) { persist({ ...preferences, hidden: [...preferences.hidden, id] }); }
  function restore(id: string) { persist({ ...preferences, hidden: preferences.hidden.filter((item) => item !== id) }); }
  function reset() { persist({ order: ids, hidden: [] }); }
  function startDrag(event: DragEvent<HTMLElement>, id: string) {
    setDragging(id);
    setDropTarget(null);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", id);
  }
  function updateDropTarget(event: DragEvent<HTMLDivElement>, target: string) {
    event.preventDefault();
    if (!dragging || dragging === target) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const position: DropTarget["position"] = event.clientY < bounds.top + bounds.height / 2 ? "before" : "after";
    setDropTarget((current) => current?.id === target && current.position === position ? current : { id: target, position });
  }
  function drop(event: DragEvent<HTMLDivElement>, target: string) {
    event.preventDefault();
    const id = dragging ?? event.dataTransfer.getData("text/plain");
    const position = dropTarget?.id === target ? dropTarget.position : "before";
    if (id && ids.includes(id)) move(id, target, position);
    setDragging(null);
    setDropTarget(null);
  }

  const dropHint = dropTarget && dragging ? `Soltar ${dropTarget.position === "before" ? "antes de" : "depois de"} ${ordered.find((widget) => widget.id === dropTarget.id)?.label ?? "este widget"}` : "";
  return <section aria-label="Widgets do painel" className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-[var(--muted)]">Arraste os widgets para reorganizar. A preferência fica salva neste navegador.</p>
      <Button size="sm" variant="secondary" aria-expanded={customizing} onClick={() => setCustomizing((open) => !open)}>{customizing ? "Fechar personalização" : "Personalizar widgets"}</Button>
    </div>
    {customizing && <section aria-label="Personalizar widgets" className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Organizar widgets</h2><p className="text-xs text-[var(--muted)]">Use os controles para uma alternativa acessível ao arrastar.</p></div><Button size="sm" variant="ghost" onClick={reset}>Restaurar padrão</Button></div>
      <ol className="mt-3 divide-y divide-[var(--border)]">{ordered.map((widget, index) => !preferences.hidden.includes(widget.id) && <li key={widget.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span className="text-sm font-medium">{widget.label}</span><span className="flex gap-1"><Button size="sm" variant="ghost" aria-label={`Mover ${widget.label} para cima`} onClick={() => moveBy(widget.id, -1)} disabled={index === 0}>↑</Button><Button size="sm" variant="ghost" aria-label={`Mover ${widget.label} para baixo`} onClick={() => moveBy(widget.id, 1)} disabled={index === ordered.length - 1}>↓</Button><Button size="sm" variant="ghost" onClick={() => hide(widget.id)}>Ocultar</Button></span></li>)}</ol>
      {hidden.length > 0 && <div className="mt-4 border-t border-[var(--border)] pt-3"><p className="text-xs font-medium text-[var(--muted)]">Widgets ocultos</p><ul className="mt-2 space-y-2">{hidden.map((widget) => <li key={widget.id} className="flex items-center justify-between gap-3"><span className="text-sm">{widget.label}</span><Button size="sm" variant="secondary" onClick={() => restore(widget.id)}>Adicionar</Button></li>)}</ul></div>}
    </section>}
    <p className="sr-only" aria-live="polite">{dropHint}</p>
    {visible.length ? <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">{visible.map((widget) => {
      const targetPosition = dropTarget?.id === widget.id ? dropTarget.position : null;
      return <div key={widget.id} onDragEnter={(event) => updateDropTarget(event, widget.id)} onDragOver={(event) => updateDropTarget(event, widget.id)} onDrop={(event) => drop(event, widget.id)} data-widget-id={widget.id} data-drop-position={targetPosition ?? undefined} className={`relative ${widget.className ?? ""} ${dragging === widget.id ? "opacity-50" : ""} ${targetPosition ? "rounded-[10px] ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-[var(--background)]" : ""}`}>
        {targetPosition && <div className={`pointer-events-none absolute inset-x-0 z-10 flex items-center gap-2 text-xs font-medium text-[var(--primary)] ${targetPosition === "before" ? "-top-3" : "-bottom-3"}`} aria-hidden="true"><span className="h-0.5 flex-1 bg-[var(--primary)]" /><span className="rounded-full bg-[var(--primary-soft)] px-2 py-0.5">{targetPosition === "before" ? "Soltar antes" : "Soltar depois"}</span><span className="h-0.5 flex-1 bg-[var(--primary)]" /></div>}
        <div className="mb-1 flex items-center gap-1 text-[11px] text-[var(--muted)]"><button draggable onDragStart={(event) => startDrag(event, widget.id)} onDragEnd={() => { setDragging(null); setDropTarget(null); }} aria-label={`Arrastar ${widget.label}`} title="Arraste para reposicionar" className="cursor-grab rounded px-1 leading-4 hover:bg-[var(--surface-raised)] active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">↕</button><span>Arraste para reposicionar</span></div>{widget.content}
      </div>;
    })}</div> : <div className="rounded-[9px] border border-dashed border-[var(--border)] p-6 text-center"><p className="text-sm text-[var(--muted)]">Todos os widgets estão ocultos.</p><Button className="mt-3" size="sm" variant="secondary" onClick={reset}>Restaurar widgets</Button></div>}
  </section>;
}
