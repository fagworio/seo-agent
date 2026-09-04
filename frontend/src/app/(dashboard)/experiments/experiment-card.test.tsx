import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Experiment } from "@/lib/api";
import { ExperimentCard } from "./experiment-card";

const base: Experiment = {
  id: 1,
  keyword: "gojo idade",
  opportunity_type: "expand_existing",
  url: "https://www.unicorniohater.com.br/gojo/",
  implemented_action: "expandir seção",
  implemented_at: "2026-01-01",
  baseline: { gsc: { clicks: 0, position: 6.7 } },
  current: {},
  delta: {},
  forecast: {},
  latest_result_window: "",
  revalidation: {},
  verdict: "improved",
  windows: { "28d": true },
  measurement_state: "measured",
};

describe("ExperimentCard", () => {
  it("shows the contextual limitation instead of the generic note", () => {
    render(<ExperimentCard experiment={{ ...base, limitations: "Movimento observado; não representa certeza causal (sem grupo de controle)." }} />);
    expect(screen.getByText(/não representa certeza causal/)).toBeInTheDocument();
    // a nota genérica NÃO deve aparecer quando há limitação contextual
    expect(screen.queryByText(/comparação observacional entre janelas/)).not.toBeInTheDocument();
  });

  it("falls back to the generic note when limitations is absent", () => {
    render(<ExperimentCard experiment={base} />);
    expect(screen.getByText(/comparação observacional entre janelas/)).toBeInTheDocument();
  });
});
