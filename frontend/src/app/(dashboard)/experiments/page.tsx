"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError, Experiment } from "@/lib/api";
import { ExperimentCard } from "./experiment-card";

export default function ExperimentsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["experiments"], queryFn: () => api.get<{ experiments: Experiment[] }>("/experiments?limit=100") });
  if (isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error) return <div className="text-sm text-[var(--danger)]">{(error as ApiError).message}</div>;
  const items = data?.experiments ?? [];

  return <div className="space-y-4">
    <header><h1 className="text-xl font-semibold">Experimentos e resultados</h1><p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">Compare o baseline com a janela mais recente. Uma melhora observada é correlação; não prova, sozinha, que a intervenção causou o resultado.</p></header>
    <div className="grid gap-4 xl:grid-cols-2">{items.map((experiment, index) => <ExperimentCard key={`${experiment.url}-${experiment.implemented_at}-${index}`} experiment={experiment} />)}{items.length === 0 && <div className="text-sm text-[var(--muted)]">Nenhuma intervenção implementada para medir.</div>}</div>
  </div>;
}
