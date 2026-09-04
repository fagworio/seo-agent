"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ActivityEntry, Role, SessionInfo, UserDetail, UserSummary } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { Input } from "@/design-system/input";
import { Badge } from "@/design-system/badge";

function useCsrf() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") }).data?.csrf_token;
}

const ROLE_LABELS: Record<string, string> = { admin: "Administrador", operator: "Operador SEO", editor: "Editor", viewer: "Leitor" };

type Tab = "perfil" | "permissoes" | "seguranca" | "sessoes" | "atividade";

export default function UsersPage() {
  const qc = useQueryClient();
  const csrf = useCsrf();
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: () => api.get<UserSummary[]>("/users") });
  const { data: roles } = useQuery({ queryKey: ["roles"], queryFn: () => api.get<{ roles: Role[] }>("/roles") });
  const [selected, setSelected] = useState<UserSummary | null>(null);
  const [creating, setCreating] = useState(false);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("editor");
  const [requireChange, setRequireChange] = useState(true);
  const [requireMfa, setRequireMfa] = useState(false);

  const create = useMutation({
    mutationFn: () => api.post<UserDetail>("/users", { email, name, roles: [role], require_password_change: requireChange, require_mfa: requireMfa }, csrf),
    onSuccess: () => { setCreating(false); setName(""); setEmail(""); qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const setRoles = useMutation({
    mutationFn: (id: number) => api.put<UserDetail>(`/users/${id}/roles`, { roles: [role] }, csrf),
    onSuccess: () => { setSelected(null); qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const disable = useMutation({
    mutationFn: (id: number) => api.post<{ ok: boolean }>(`/users/${id}/disable`, {}, csrf),
    onSuccess: () => { setSelected(null); qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  if (!users || !roles) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="w-64"><Input placeholder="Buscar usuário…" /></div>
        <Button onClick={() => setCreating(!creating)}>+ Novo usuário</Button>
      </div>

      {creating && (
        <Card title="Novo usuário">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><label className="mb-1 block font-medium">Nome</label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div><label className="mb-1 block font-medium">Email</label><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            <div className="col-span-2">
              <label className="mb-1 block font-medium">Função</label>
              <div className="flex gap-4">{["editor", "operator", "viewer", "admin"].map((r) => (
                <label key={r} className="flex items-center gap-1"><input type="radio" checked={role === r} onChange={() => setRole(r)} />{ROLE_LABELS[r]}</label>
              ))}</div>
            </div>
            <label className="flex items-center gap-2"><input type="checkbox" checked={requireChange} onChange={(e) => setRequireChange(e.target.checked)} />Exigir troca de senha no 1º acesso</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={requireMfa} onChange={(e) => setRequireMfa(e.target.checked)} />Exigir MFA</label>
          </div>
          <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={() => setCreating(false)}>Cancelar</Button><Button onClick={() => create.mutate()} disabled={create.isPending}>Criar usuário</Button></div>
          {create.error && <p className="mt-2 text-sm text-[var(--danger)]">{(create.error as Error).message}</p>}
        </Card>
      )}

      <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
            <tr><th className="px-3 py-2">Nome</th><th className="px-3 py-2">Email</th><th className="px-3 py-2">Função</th><th className="px-3 py-2">MFA</th><th className="px-3 py-2">Status</th></tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => (
              <tr key={u.id} onClick={() => setSelected(u)} className="cursor-pointer border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
                <td className="px-3 py-2">{u.name}</td><td className="px-3 py-2">{u.email}</td>
                <td className="px-3 py-2">{u.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</td>
                <td className="px-3 py-2">{u.is_mfa_enabled ? "✓" : "—"}</td>
                <td className="px-3 py-2"><Badge tone={u.is_active ? "success" : "neutral"}>{u.is_active ? "Ativo" : "Inativo"}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && <UserDrawer user={selected} roles={roles.roles} onClose={() => setSelected(null)} onDisable={disable} onRoles={setRoles} csrf={csrf} />}
    </div>
  );
}

function UserDrawer({ user, roles, onClose, onDisable, onRoles, csrf }: {
  user: UserSummary; roles: Role[]; onClose: () => void;
  onDisable: { mutate: (id: number) => void }; onRoles: { mutate: (id: number) => void }; csrf: string | undefined;
}) {
  const [tab, setTab] = useState<Tab>("perfil");
  const detail = useQuery({ queryKey: ["user", user.id], queryFn: () => api.get<UserDetail>(`/users/${user.id}`) });
  const sessions = useQuery({ queryKey: ["user-sessions", user.id], queryFn: () => api.get<SessionInfo[]>(`/users/${user.id}/sessions`) });
  const activity = useQuery({ queryKey: ["user-activity", user.id], queryFn: () => api.get<ActivityEntry[]>(`/users/${user.id}/activity`) });
  const d = detail.data;
  const role = roles.find((r) => r.name === (d?.roles[0] ?? user.roles[0]));
  const tabs: [Tab, string][] = [["perfil", "Perfil"], ["permissoes", "Permissões"], ["seguranca", "Segurança"], ["sessoes", "Sessões"], ["atividade", "Atividade"]];

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <div className="h-full w-full max-w-2xl overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div><h2 className="text-lg font-semibold">{d?.name || user.name}</h2><p className="text-xs text-[var(--muted)]">{d?.email || user.email}</p></div>
          <button onClick={onClose} className="text-[var(--muted)]">✕</button>
        </div>
        <div className="mb-4 flex gap-1">{tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 text-sm ${tab === k ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>{l}</button>)}</div>

        {tab === "perfil" && (
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-[var(--muted)]">Nome</span><div>{d?.name || "—"}</div></div>
            <div><span className="text-[var(--muted)]">Email</span><div>{d?.email || "—"}</div></div>
            <div><span className="text-[var(--muted)]">Status</span><div><Badge tone={d?.is_active ? "success" : "neutral"}>{d?.is_active ? "Ativo" : "Inativo"}</Badge></div></div>
            <div><span className="text-[var(--muted)]">Criado</span><div>{d?.created_at ? new Date(d.created_at).toLocaleString("pt-BR") : "—"}</div></div>
            <div><span className="text-[var(--muted)]">Último acesso</span><div>{d?.last_login_at ? new Date(d.last_login_at).toLocaleString("pt-BR") : "—"}</div></div>
          </div>
        )}

        {tab === "permissoes" && (
          <div className="text-sm">
            <div className="mb-2 text-[var(--muted)]">Função atual: <strong>{ROLE_LABELS[role?.name ?? ""] ?? role?.name ?? "—"}</strong></div>
            <div className="mb-3 flex gap-4">{["editor", "operator", "viewer", "admin"].map((r) => (
              <label key={r} className="flex items-center gap-1 text-xs"><input type="radio" defaultChecked={role?.name === r} name="u-role" />{ROLE_LABELS[r] ?? r}</label>
            ))}</div>
            <ul className="grid grid-cols-2 gap-1 text-xs">
              {(role?.permissions ?? []).map((p) => <li key={p} className="flex items-center gap-1"><span className="text-[var(--success)]">✓</span>{p}</li>)}
            </ul>
            <div className="mt-3 flex justify-end"><Button size="sm" variant="secondary" onClick={() => onRoles.mutate(user.id)}>Alterar função</Button></div>
          </div>
        )}

        {tab === "seguranca" && (
          <div className="space-y-2 text-sm">
            <Row k="MFA" v={d?.is_mfa_enabled ? "Ativado" : "Desativado"} />
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm">Forçar redefinição de senha</Button>
              <Button variant="secondary" size="sm">Resetar MFA</Button>
              <Button size="sm" onClick={() => onDisable.mutate(user.id)}>Desativar usuário</Button>
            </div>
          </div>
        )}

        {tab === "sessoes" && (
          <ul className="space-y-2 text-sm">{(sessions.data ?? []).filter((s) => !s.revoked_at).map((s) => (
            <li key={s.id} className="flex justify-between border-t border-[var(--border)] pt-2"><span>{s.user_agent || "—"}</span><span className="text-xs text-[var(--muted)]">{new Date(s.last_seen_at).toLocaleString("pt-BR")}</span></li>))}
            {(sessions.data ?? []).filter((s) => !s.revoked_at).length === 0 && <li className="text-[var(--muted)]">Sem sessões ativas.</li>}
          </ul>
        )}

        {tab === "atividade" && (
          <ol className="space-y-2 text-sm">{(activity.data ?? []).map((e, i) => (
            <li key={i} className="flex gap-3 border-b border-[var(--border)] pb-2"><span className="w-32 text-xs text-[var(--muted)]">{new Date(e.ts).toLocaleString("pt-BR")}</span><span className="font-mono text-xs">{e.event}</span><span className="min-w-0 flex-1 truncate text-xs">{e.summary || e.event}</span></li>))}
            {(activity.data ?? []).length === 0 && <li className="text-[var(--muted)]">Sem atividade.</li>}
          </ol>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between"><span className="text-[var(--muted)]">{k}</span><span>{v}</span></div>;
}
