"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/design-system/button";

export function LogoutButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function logout() {
    setPending(true);
    setError(null);
    try {
      const me = await api.get<{ csrf_token: string }>("/auth/me");
      await api.post("/auth/logout", {}, me.csrf_token);
      // recarrega para limpar estado global (react-query cache) e ir ao login
      window.location.href = "/login";
    } catch (e) {
      setError((e as ApiError).message ?? "Não foi possível encerrar a sessão.");
      setPending(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button size="sm" variant="secondary" onClick={() => logout()} disabled={pending}>
        {pending ? "Saindo…" : "Sair"}
      </Button>
      {error && <span className="max-w-40 truncate text-xs text-[var(--danger)]" title={error}>{error}</span>}
    </span>
  );
}
