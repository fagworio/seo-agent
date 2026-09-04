"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Account, AuthSettings, SessionInfo } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { Input } from "@/design-system/input";
import { Badge } from "@/design-system/badge";

function useCsrf() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string }>("/auth/me") }).data?.csrf_token;
}

export default function SecurityPage() {
  const qc = useQueryClient();
  const csrf = useCsrf();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });
  const { data: account } = useQuery({ queryKey: ["account"], queryFn: () => api.get<Account>("/account") });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<{ sessions: SessionInfo[] }>("/auth/sessions") });
  const authSettings = useQuery({ queryKey: ["settings-auth"], queryFn: () => api.get<AuthSettings>("/settings/auth") });

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  const changePassword = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/account/change-password", { current_password: curPw, new_password: newPw }, csrf),
    onSuccess: () => { setCurPw(""); setNewPw(""); setConfirmPw(""); qc.invalidateQueries({ queryKey: ["account"] }); },
  });
  const mfaSetup = useMutation({
    mutationFn: () => api.post<{ secret: string }>("/account/mfa/setup", {}, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account"] }),
  });
  const mfaConfirm = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/account/mfa/confirm", { code: mfaCode }, csrf),
    onSuccess: () => { setMfaCode(""); qc.invalidateQueries({ queryKey: ["account"] }); },
  });
  const mfaDisable = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/account/mfa/disable", {}, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", "me"] }),
  });
  const toggleMfaGate = useMutation({
    mutationFn: (enabled: boolean) => api.put<AuthSettings>("/settings/auth/mfa-login", { enabled }, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings-auth"] }),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.del<{ ok: boolean }>(`/auth/sessions/${id}`, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const revokeOthers = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/auth/sessions/revoke-others", {}, csrf),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions", "me"] }),
  });

  const passwordsMatch = newPw.length > 0 && newPw === confirmPw;
  const mfaSecret = mfaSetup.data?.secret;
  const canManageSettings = me.data?.user.permissions.includes("settings.manage") ?? false;
  const mfaGateOn = authSettings.data?.mfa_login_required ?? false;

  return (
    <div className="max-w-2xl space-y-4">
      <Card title="Senha">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><label className="mb-1 block font-medium">Senha atual</label><Input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} /></div>
          <div className="text-xs text-[var(--muted)]">Mín. 15 caracteres sem 2FA · 8 com 2FA · máx 64</div>
          <div><label className="mb-1 block font-medium">Nova senha</label><Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} /></div>
          <div><label className="mb-1 block font-medium">Confirmar</label><Input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} /></div>
        </div>
        <div className="my-2 text-xs text-[var(--muted)]">✓ comprimento permitido · ✓ senhas coincidem</div>
        <div className="flex justify-end"><Button onClick={() => changePassword.mutate()} disabled={changePassword.isPending || !passwordsMatch}>Alterar senha</Button></div>
        {changePassword.error && <p className="text-sm text-[var(--danger)]">{(changePassword.error as Error).message}</p>}
      </Card>

      <Card title="Autenticação em duas etapas">
        {account?.is_mfa_enabled ? (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2"><Badge tone="success">● Ativada</Badge><span className="text-[var(--muted)]">Aplicativo autenticador</span></div>
            <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => mfaDisable.mutate()} disabled={mfaDisable.isPending}>Desativar MFA</Button></div>
            {mfaDisable.error && <p className="text-sm text-[var(--danger)]">{(mfaDisable.error as Error).message}</p>}
          </div>
        ) : mfaSecret ? (
          <div className="space-y-3 text-sm">
            <div className="rounded-md border border-[var(--border)] p-3 text-center font-mono text-lg tracking-wider">{mfaSecret}</div>
            <div><label className="mb-1 block font-medium">Digite o código do aplicativo</label><Input placeholder="000000" maxLength={6} value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} /></div>
            <div className="flex justify-end"><Button onClick={() => mfaConfirm.mutate()} disabled={mfaConfirm.isPending}>Confirmar e ativar</Button></div>
          </div>
        ) : (
          <div className="flex justify-end"><Button onClick={() => mfaSetup.mutate()} disabled={mfaSetup.isPending}>Configurar</Button></div>
        )}
      </Card>

      <Card title="Política de MFA no login">
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge tone={mfaGateOn ? "success" : "neutral"}>{mfaGateOn ? "● Ativada" : "○ Desativada (padrão)"}</Badge>
              <span className="text-[var(--muted)]">Exigir 2º fator no login</span>
            </div>
            {canManageSettings ? (
              <Button variant={mfaGateOn ? "secondary" : "primary"} size="sm"
                onClick={() => toggleMfaGate.mutate(!mfaGateOn)}
                disabled={toggleMfaGate.isPending || authSettings.isLoading}>
                {mfaGateOn ? "Desabilitar (login padrão)" : "Habilitar para produção"}
              </Button>
            ) : (
              <span className="text-[11px] text-[var(--muted)]">Somente administradores alteram esta política.</span>
            )}
          </div>
          <p className="text-xs text-[var(--muted)]">
            Desabilitada por padrão: o acesso usa senha apenas, mesmo para contas com MFA cadastrado.
            Ao habilitar (produção), contas com MFA passam a exigir o código do aplicativo no login. Alteração exige reautenticação recente e fica registrada em Auditoria.
          </p>
          {toggleMfaGate.error && <p className="text-sm text-[var(--danger)]">{(toggleMfaGate.error as Error).message}</p>}
        </div>
      </Card>

      <Card title="Sessões ativas">
        <div className="mb-3 flex justify-end"><Button variant="secondary" size="sm" onClick={() => revokeOthers.mutate()} disabled={revokeOthers.isPending}>Encerrar todas as outras sessões</Button></div>
        <ul className="space-y-3">
          {(sessions.data?.sessions ?? []).filter((s) => !s.revoked_at).map((s) => (
            <li key={s.id} className="flex items-center justify-between border-t border-[var(--border)] pt-3 text-sm">
              <div><p>{s.user_agent || "Navegador não identificado"}</p><p className="text-xs text-[var(--muted)]">Última atividade: {new Date(s.last_seen_at).toLocaleString("pt-BR")}</p></div>
              <Button variant="secondary" size="sm" onClick={() => revoke.mutate(s.id)} disabled={revoke.isPending}>Encerrar</Button>
            </li>
          ))}
          {(sessions.data?.sessions ?? []).filter((s) => !s.revoked_at).length === 0 && <li className="text-sm text-[var(--muted)]">Sem sessões ativas.</li>}
        </ul>
      </Card>
    </div>
  );
}
