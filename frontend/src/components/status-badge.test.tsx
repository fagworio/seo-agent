import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge, statusMeta } from "./status-badge";

describe("statusMeta (estados visuais padronizados)", () => {
  it("mapeia os 12 estados do spec para rótulo em PT", () => {
    const cases: [string, string][] = [
      ["draft", "Novo"],
      ["review_required", "Revisão"],
      ["approved", "Aprovado"],
      ["queued", "Delegado"],
      ["running", "Em execução"],
      ["completed", "Implementado"],
      ["verified", "Verificado"],
      ["stale", "Precisa revisão"],
      ["failed", "Falhou"],
      ["measuring", "Aguardando dados"],
      ["measured", "Medido"],
      ["pending", "Aguardando"],
    ];
    for (const [status, label] of cases) {
      expect(statusMeta(status).label).toBe(label);
    }
  });

  it("retorna status desconhecido como fallback e null como travessão", () => {
    expect(statusMeta("algo_inedito").label).toBe("algo_inedito");
    expect(statusMeta(null).label).toBe("—");
    expect(statusMeta(undefined).label).toBe("—");
  });
});

describe("StatusBadge", () => {
  it("renderiza rótulo + tom (nunca só cor)", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("Em execução")).toBeTruthy();
  });
});
