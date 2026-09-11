import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExternalTelemetry } from "./external-telemetry";

describe("ExternalTelemetry", () => {
  it("não renderiza quando o run não tem telemetria (runs antigos)", () => {
    const { container } = render(<ExternalTelemetry summary={{ steps: ["audit"] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra chamadas, evitadas por cache, HTTP 304, bytes, retentativas e duração", () => {
    render(
      <ExternalTelemetry
        summary={{
          telemetry: {
            calls: 142, cache_hits: 17, http_304: 40, bytes: 4_812_345, retries: 2,
            duration_s: 63.2, max_calls: 0, by_kind: { get: 140, post: 2 },
          },
        }}
      />,
    );
    expect(screen.getByLabelText("Telemetria externa")).toBeInTheDocument();
    expect(screen.getByText("Chamadas externas")).toBeInTheDocument();
    expect(screen.getByText("142")).toBeInTheDocument();
    expect(screen.getByText("Chamadas evitadas (cache)")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
    // HTTP 304 é separado das chamadas evitadas (a requisição HTTP aconteceu).
    expect(screen.getByText("HTTP 304 (corpo reusado)")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.getByText("4.6 MB")).toBeInTheDocument();
    expect(screen.getByText("63s")).toBeInTheDocument();
  });

  it("mostra o teto quando MAX_EXTERNAL_CALLS está configurado", () => {
    render(<ExternalTelemetry summary={{ telemetry: { calls: 10, max_calls: 100 } }} />);
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("Teto")).toBeInTheDocument();
  });
});
