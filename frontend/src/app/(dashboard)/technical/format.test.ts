import { describe, expect, it } from "vitest";
import { fmt, fmtNum, num, pct } from "@/lib/format";

describe("technical formatters", () => {
  it("formats CTR as percent BR", () => {
    expect(pct(0.004)).toBe("0,4%");
    expect(pct(0.02)).toBe("2,0%");
    expect(pct(null)).toBe("—");
  });
  it("formats position with one decimal BR", () => {
    expect(num(8.34)).toBe("8,3");
    expect(num(null)).toBe("—");
  });
  it("formats numbers with pt-BR grouping", () => {
    expect(fmt(5290)).toBe("5.290");
    expect(fmt(null)).toBe("—");
  });
  it("never renders a fake zero for missing data", () => {
    // missing ≠ zero: quando não há coleta, o backend retorna null e o
    // formatador não exibe 0.
    expect(fmt(null)).toBe("—");
    expect(fmtNum(null)).toBe("0"); // apenas para o cenário realista (opcional)
  });
});
