"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";

type Session = { id: number; created_at: string; last_seen_at: string; expires_at: string; revoked_at: string | null; user_agent: string; ip_hash: string };
export default function SettingsPage() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { name: string; email: string } }>("/auth/me") });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<{ sessions: Session[] }>("/auth/sessions") });
  const revokeOthers = useMutation({ mutationFn: () => api.post<{ ok: boolean }>("/auth/sessions/revoke-others", {}, me.data?.csrf_token), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }) });
  const revoke = useMutation({ mutationFn: (id: number) => api.del<{ ok: boolean }>(`/auth/sessions/${id}`, me.data?.csrf_token), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }) });
  return <div className="space-y-6"><Card title="Conta"><p className="text-sm">{me.data?.user.name || "—"} <span className="text-[var(--muted)]">{me.data?.user.email || ""}</span></p><p className="mt-2 text-xs text-[var(--muted)]">Senhas, MFA e integrações sensíveis são alterados por fluxos protegidos; segredos não são expostos neste painel.</p></Card><Card title="Sessões ativas"><div className="mb-3 flex justify-end"><Button variant="secondary" size="sm" onClick={() => revokeOthers.mutate()} disabled={revokeOthers.isPending}>Encerrar outras sessões</Button></div>{sessions.isLoading ? <p className="text-sm text-[var(--muted)]">Carregando sessões…</p> : <ul className="space-y-3">{(sessions.data?.sessions ?? []).filter((session) => !session.revoked_at).map((session) => <li key={session.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-3 text-sm"><div><p>{session.user_agent || "Navegador não identificado"}</p><p className="text-xs text-[var(--muted)]">Última atividade: {session.last_seen_at || session.created_at}</p></div><Button variant="secondary" size="sm" onClick={() => revoke.mutate(session.id)} disabled={revoke.isPending}>Encerrar</Button></li>)}{!(sessions.data?.sessions ?? []).some((session) => !session.revoked_at) && <li className="text-sm text-[var(--muted)]">Não há sessões ativas.</li>}</ul>}{(sessions.error || revoke.error || revokeOthers.error) && <p className="mt-3 text-sm text-[var(--danger)]">{((sessions.error || revoke.error || revokeOthers.error) as ApiError).message}</p>}</Card></div>;
}
