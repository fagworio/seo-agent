import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { classify } from "./contract";
import { ScoreBar, ScoreBreakdown, ConfidenceBadge, TrendIndicator, IntelligenceScores } from "./index";

describe("classify (níveis 0-100)", () => {
  it("mapeia faixas para níveis/cor", () => {
    expect(classify(10).level).toBe("muito_baixo");
    expect(classify(40).level).toBe("baixo");
    expect(classify(60).level).toBe("moderado");
    expect(classify(75).level).toBe("alto");
    expect(classify(90).level).toBe("muito_alto");
    expect(classify(null).label).toBe("—");
  });
});

describe("ScoreBar", () => {
  it("mostra label, score e nível", () => {
    render(<ScoreBar label="Rankability" score={84} level="alto" />);
    expect(screen.getByText("Rankability")).toBeTruthy();
    expect(screen.getByText("84")).toBeTruthy();
  });
  it("mostra travessão quando score ausente", () => {
    render(<ScoreBar label="Headroom" score={null} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("ScoreBreakdown", () => {
  it("lista os fatores com barra", () => {
    render(<ScoreBreakdown title="Topic Authority" score={87} level="muito_alto" factors={[
      { label: "Coverage", value: 91 }, { label: "Visibility", value: 94 }]} />);
    expect(screen.getByText("Topic Authority")).toBeTruthy();
    expect(screen.getByText("Coverage")).toBeTruthy();
    expect(screen.getByText("91")).toBeTruthy();
  });
});

describe("ConfidenceBadge", () => {
  it("mostra confiança em %", () => {
    render(<ConfidenceBadge score={0.89} label="high" />);
    expect(screen.getByText(/89%/)).toBeTruthy();
  });
});

describe("TrendIndicator", () => {
  it("indica subida/queda/estável", () => {
    const { container } = render(<><TrendIndicator deltaPct={31} /><TrendIndicator deltaPct={-12} /><TrendIndicator deltaPct={0} /></>);
    expect(container.textContent).toContain("↑ 31%");
    expect(container.textContent).toContain("↓ 12%");
    expect(container.textContent).toContain("→");
  });
});

describe("IntelligenceScores (fluxo funcional: análise V2 integrada)", () => {
  // Payload igual ao que o backend retorna em compute_opportunity_v2
  it("renderiza os scores V2 persistidos (Topic/Query/Opportunity/Confidence)", () => {
    render(<IntelligenceScores scores={{
      topicAuthority: 87,
      rankability: { score: 84, level: "alto" },
      headroom: 91,
      opportunity: { score: 91, level: "forte" },
      confidence: { score: 0.89, label: "high" },
    }} />);
    expect(screen.getByText("Topic Authority")).toBeTruthy();
    expect(screen.getByText("Rankability")).toBeTruthy();
    expect(screen.getByText("Oportunidade")).toBeTruthy();
    expect(screen.getAllByText("91").length).toBeGreaterThan(0); // headroom + opportunity
    expect(screen.getAllByText(/89%/).length).toBeGreaterThan(0); // confidence
  });
});
