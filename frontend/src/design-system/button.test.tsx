import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "./badge";
import { Button } from "./button";

describe("Button", () => {
  it("renders its label", () => {
    render(<Button>Entrar</Button>);
    expect(screen.getByRole("button", { name: "Entrar" })).toBeInTheDocument();
  });

  it("applies the danger variant class", () => {
    const { container } = render(<Button variant="danger">Excluir</Button>);
    expect(container.firstChild).toHaveClass("bg-[var(--danger)]");
  });

  it("is disabled when disabled", () => {
    render(<Button disabled>Salvar</Button>);
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
  });
});

describe("Badge", () => {
  it("renders text with a status tone and is not silent-by-color only", () => {
    render(<Badge tone="danger">falhou</Badge>);
    expect(screen.getByText("falhou")).toBeInTheDocument();
  });
});
