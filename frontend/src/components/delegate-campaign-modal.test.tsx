import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DelegateCampaignModal } from "./delegate-campaign-modal";

function renderModal(fingerprints: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DelegateCampaignModal fingerprints={fingerprints} onClose={() => {}} onCreated={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // Sem rede no teste: qualquer fetch do Modal (me/preview) rejeita de forma quieta.
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
});

describe("DelegateCampaignModal", () => {
  it("não abre em branco: mostra estado vazio quando não há fingerprints", () => {
    renderModal([]);
    expect(screen.getByText("Nada para delegar")).toBeInTheDocument();
    expect(screen.getByText(/correções já executadas ou rejeitadas/i)).toBeInTheDocument();
  });

  it("renderiza cabeçalho visível e botão Fechar (o título não era renderizado)", () => {
    renderModal([]);
    expect(screen.getByRole("heading", { name: "Delegar melhorias" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fechar" })).toBeInTheDocument();
  });
});
