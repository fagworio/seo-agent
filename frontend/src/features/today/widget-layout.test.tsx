import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DashboardWidgetLayout, type DashboardWidget } from "./widget-layout";

const widgets: DashboardWidget[] = [
  { id: "impact", label: "Impacto", content: <div>Conteúdo impacto</div> },
  { id: "automation", label: "Automação", content: <div>Conteúdo automação</div> },
];

describe("DashboardWidgetLayout", () => {
  beforeEach(() => window.localStorage.clear());

  it("permite ocultar, restaurar e reordenar widgets pelos controles", () => {
    const { container } = render(<DashboardWidgetLayout widgets={widgets} />);
    fireEvent.click(screen.getByRole("button", { name: "Personalizar widgets" }));
    fireEvent.click(screen.getByRole("button", { name: "Mover Impacto para baixo" }));
    expect([...container.querySelectorAll("[data-widget-id]")].map((node) => node.getAttribute("data-widget-id"))).toEqual(["automation", "impact"]);
    fireEvent.click(within(screen.getByText("Impacto", { selector: "span" }).closest("li")!).getByRole("button", { name: "Ocultar" }));
    expect(screen.queryByText("Conteúdo impacto")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar" }));
    expect(screen.getByText("Conteúdo impacto")).toBeInTheDocument();
  });

  it("destaca a borda correta e solta antes ou depois conforme o cursor", () => {
    const { container } = render(<DashboardWidgetLayout widgets={widgets} />);
    const source = screen.getByRole("button", { name: "Arrastar Impacto" });
    const target = container.querySelector('[data-widget-id="automation"]') as HTMLDivElement;
    Object.defineProperty(target, "getBoundingClientRect", { value: () => ({ top: 0, height: 100 }) });
    const dataTransfer = { effectAllowed: "", setData: () => undefined, getData: () => "impact" };

    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(target, { clientY: 75, dataTransfer });
    expect(target).toHaveAttribute("data-drop-position", "after");
    expect(screen.getByText("Soltar depois")).toBeVisible();
    fireEvent.drop(target, { clientY: 75, dataTransfer });
    expect([...container.querySelectorAll("[data-widget-id]")].map((node) => node.getAttribute("data-widget-id"))).toEqual(["automation", "impact"]);
  });
});
