"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, LoginResponse } from "@/lib/api";
import { Button } from "@/design-system/button";
import { Input } from "@/design-system/input";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaUserId, setMfaUserId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"credentials" | "mfa">("credentials");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post<LoginResponse>("/auth/login", { email, password });
      if (!res.ok) {
        setError(res.message ?? "Email ou senha inválidos.");
        return;
      }
      if (res.requires_mfa && res.mfa_user_id) {
        setMfaUserId(res.mfa_user_id);
        setStep("mfa");
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const submitMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post<LoginResponse>("/auth/mfa/verify", {
        user_id: mfaUserId,
        code: otp,
      });
      if (!res.ok) {
        setError(res.message ?? "Código inválido ou expirado.");
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--background)] p-4">
      <div className="w-full max-w-sm rounded-[11px] border border-[var(--border)] bg-[var(--surface)] p-8">
        <div className="mb-6 text-center">
          <div className="text-lg font-semibold">SEO AGENT</div>
          <div className="text-sm text-[var(--muted)]">
            {step === "credentials" ? "Entre no painel de operações" : "Verificação em duas etapas"}
          </div>
        </div>

        {step === "mfa" ? (
          <form onSubmit={submitMfa} className="space-y-4">
            <div className="text-sm text-[var(--muted)]">
              Insira o código do seu aplicativo autenticador.
            </div>
            <Input
              inputMode="numeric"
              maxLength={6}
              placeholder="000000"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
            />
            {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "Verificando..." : "Confirmar"}
            </Button>
          </form>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium">Email</label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium">Senha</label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
