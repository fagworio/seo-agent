"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Input } from "@/design-system/input";

export default function ResetPasswordPage() { return <Suspense><ResetForm /></Suspense>; }
function ResetForm() { const token = useSearchParams().get("token") ?? ""; const [password, setPassword] = useState(""); const [message, setMessage] = useState(""); const [error, setError] = useState(""); async function submit(event: React.FormEvent) { event.preventDefault(); setError(""); if (!token) { setError("Link de redefinição inválido ou expirado."); return; } try { const response = await api.post<{ ok: boolean; message: string }>("/auth/reset-password", { token, new_password: password }); if (!response.ok) setError(response.message); else setMessage("Senha redefinida. Entre com sua nova senha."); } catch { setError("Não foi possível redefinir a senha."); } } return <main className="flex min-h-screen items-center justify-center bg-[var(--background)] p-4"><section className="w-full max-w-sm rounded-[11px] border border-[var(--border)] bg-[var(--surface)] p-8"><h1 className="text-lg font-semibold">Nova senha</h1>{message ? <p className="mt-3 text-sm text-[var(--success)]">{message}</p> : <form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm font-medium">Nova senha<Input className="mt-1" type="password" minLength={15} autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label><p className="text-xs text-[var(--muted)]">Use uma senha longa, com pelo menos 15 caracteres.</p>{error && <p className="text-sm text-[var(--danger)]">{error}</p>}<Button className="w-full" type="submit">Redefinir senha</Button></form>}<Link className="mt-5 block text-sm text-[var(--primary)]" href="/login">Ir para login</Link></section></main>; }
