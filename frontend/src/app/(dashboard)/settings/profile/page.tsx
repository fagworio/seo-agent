"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Account } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { Input } from "@/design-system/input";
import { Badge } from "@/design-system/badge";

function useCsrf() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") }).data?.csrf_token;
}

const ROLE_LABELS: Record<string, string> = { admin: "Administrador", operator: "Operador SEO", editor: "Editor", viewer: "Leitor" };

export default function ProfilePage() {
  const qc = useQueryClient();
  const csrf = useCsrf();
  const { data: account } = useQuery({ queryKey: ["account"], queryFn: () => api.get<Account>("/account") });
  const [name, setName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");

  const saveName = useMutation({
    mutationFn: () => api.patch<{ ok: boolean }>("/account", { name }, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", "me"] }),
  });
  const changeEmail = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/account/change-email", { new_email: newEmail, password }, csrf),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["account"] }); setNewEmail(""); setPassword(""); },
  });

  if (!account) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  const a = account;
  return (
    <div className="max-w-2xl space-y-4">
      <Card title="Informações pessoais">
        <div className="space-y-4 text-sm">
          <div>
            <label className="mb-1 block font-medium">Nome</label>
            <Input defaultValue={a.name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block font-medium">Email</label>
            <div className="flex items-center justify-between gap-2">
              <span>{a.email}</span>
              <span className="text-xs text-[var(--muted)]">Troca exige senha atual</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div><span className="text-[var(--muted)]">Função</span><div>{a.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</div></div>
            <div><span className="text-[var(--muted)]">2FA</span><div><Badge tone={a.is_mfa_enabled ? "success" : "warning"}>{a.is_mfa_enabled ? "Ativada" : "Desativada"}</Badge></div></div>
          </div>
          <div className="grid grid-cols-2 gap-4 text-xs text-[var(--muted)]">
            <div><span>Conta criada</span><div className="text-[var(--foreground)]">{new Date(a.created_at).toLocaleString("pt-BR")}</div></div>
            <div><span>Último acesso</span><div className="text-[var(--foreground)]">{a.last_login_at ? new Date(a.last_login_at).toLocaleString("pt-BR") : "—"}</div></div>
          </div>
          <div className="flex justify-end"><Button onClick={() => saveName.mutate()} disabled={saveName.isPending}>Salvar alterações</Button></div>
          {saveName.error && <p className="text-sm text-[var(--danger)]">{(saveName.error as Error).message}</p>}
        </div>
      </Card>

      <Card title="Alterar email">
        <div className="space-y-3 text-sm">
          <div><label className="mb-1 block font-medium">Novo email</label><Input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} /></div>
          <div><label className="mb-1 block font-medium">Senha atual</label><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div className="flex justify-end"><Button variant="secondary" onClick={() => changeEmail.mutate()} disabled={changeEmail.isPending}>Alterar email</Button></div>
          {changeEmail.error && <p className="text-sm text-[var(--danger)]">{(changeEmail.error as Error).message}</p>}
          {changeEmail.isSuccess && <p className="text-sm text-[var(--success)]">Email atualizado.</p>}
        </div>
      </Card>
    </div>
  );
}
