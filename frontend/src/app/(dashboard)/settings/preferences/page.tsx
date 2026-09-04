"use client";

import { useState } from "react";
import { Card } from "@/design-system/card";

export default function PreferencesPage() {
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");
  const [lang, setLang] = useState("pt");
  const [tz, setTz] = useState("America/Sao_Paulo");
  const [notif, setNotif] = useState({ important: true, agentFail: true, ready: true });

  return (
    <div className="max-w-2xl space-y-4">
      <Card title="Aparência">
        <label className="mb-1 block text-sm font-medium">Tema</label>
        <div className="flex gap-4 text-sm">
          {(["system", "light", "dark"] as const).map((t) => (
            <label key={t} className="flex items-center gap-1"><input type="radio" checked={theme === t} onChange={() => setTheme(t)} />{t[0].toUpperCase() + t.slice(1)}</label>
          ))}
        </div>
      </Card>
      <Card title="Localização">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><label className="mb-1 block font-medium">Idioma</label>
            <select className="h-9 w-full rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={lang} onChange={(e) => setLang(e.target.value)}><option value="pt">Português</option><option value="en">English</option></select></div>
          <div><label className="mb-1 block font-medium">Fuso horário</label>
            <select className="h-9 w-full rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={tz} onChange={(e) => setTz(e.target.value)}><option>America/Sao_Paulo</option><option>UTC</option></select></div>
        </div>
      </Card>
      <Card title="Notificações">
        <div className="space-y-2 text-sm">
          {([["important", "oportunidades importantes"], ["agentFail", "execução de agente com falha"], ["ready", "resultados prontos para revisão"]] as const).map(([k, l]) => (
            <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={notif[k]} onChange={(e) => setNotif({ ...notif, [k]: e.target.checked })} />{l}</label>
          ))}
        </div>
      </Card>
    </div>
  );
}
