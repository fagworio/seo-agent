import { describe, expect, it } from "vitest";
import { TYPE_GUIDE, FALLBACK_GUIDE, guideOf, intentLabel } from "./guide";

describe("TYPE_GUIDE (clareza do pipeline editorial)", () => {
  it("explica os 4 tipos de pauta sem usar o slug cru", () => {
    const cases: [string, string][] = [
      ["hub_page", "Criar página-guia (hub)"],
      ["supporting_post", "Criar post de apoio"],
      ["cannibalization_review", "Revisar canibalização"],
      ["expand_existing", "Expandir página existente"],
    ];
    for (const [type, label] of cases) {
      const g = TYPE_GUIDE[type];
      expect(g).toBeDefined();
      expect(g.label).toBe(label);
      expect(g.what.length).toBeGreaterThan(20);   // "o que é" explicado
      expect(g.how.length).toBeGreaterThan(20);    // "como fazer" explicado
      expect(g.hint.length).toBeGreaterThan(5);    // legenda curta
      expect(["info", "primary", "warning", "success"]).toContain(g.tone);
    }
  });

  it("tipo desconhecido cai para o guia genérico (fallback)", () => {
    expect(guideOf("tipo_inexistente").label).toBe(FALLBACK_GUIDE.label);
    expect(guideOf("").label).toBe("Pauta editorial");
  });

  it("traduz a intenção técnica em frase clara", () => {
    expect(intentLabel("navegação/cluster")).toMatch(/cluster/);
    expect(intentLabel("revisão")).toMatch(/canibalização/i);
    expect(intentLabel("question")).toMatch(/pergunta/i);
    expect(intentLabel("")).toBe("não informado");
  });
});
