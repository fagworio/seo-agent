"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Input } from "@/design-system/input";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState(""); const [done, setDone] = useState(false); const [error, setError] = useState("");
  async function submit(event: React.FormEvent) { event.preventDefault(); setError(""); try { await api.post("/auth/forgot-password", { email }); setDone(true); } catch { setError("Não foi possível processar a solicitação. Tente novamente."); } }
  return <main className="flex min-h-screen items-center justify-center bg-[var(--background)] p-4"><section className="w-full max-w-sm rounded-[11px] border border-[var(--border)] bg-[var(--surface)] p-8"><h1 className="text-lg font-semibold">Redefinir senha</h1>{done ? <p className="mt-3 text-sm text-[var(--muted)]">Se existir uma conta para este email, você receberá as instruções para redefinir sua senha.</p> : <form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm font-medium">Email<Input className="mt-1" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>{error && <p className="text-sm text-[var(--danger)]">{error}</p>}<Button className="w-full" type="submit">Enviar instruções</Button></form>}<Link className="mt-5 block text-sm text-[var(--primary)]" href="/login">Voltar ao login</Link></section></main>;
}
