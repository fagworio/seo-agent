import { describe, expect, it } from "vitest";
import { cumulativeClickSeries } from "./title-impact-widget";

describe("cumulativeClickSeries", () => {
  it("acumula somente os meses com dados, sem tratar a ausência como zero", () => {
    expect(cumulativeClickSeries([
      { date: "2026-01", modified_titles: 2, observed_index: 110, forecast_index: 108, benchmark_index: null, observed_clicks_delta: 10, forecast_clicks_delta: 8 },
      { date: "2026-02", modified_titles: 3, observed_index: null, forecast_index: null, benchmark_index: null, observed_clicks_delta: null, forecast_clicks_delta: null },
      { date: "2026-03", modified_titles: 1, observed_index: 115, forecast_index: 112, benchmark_index: null, observed_clicks_delta: 5, forecast_clicks_delta: 4 },
    ])).toEqual([
      { date: "2026-01", value: 10 },
      { date: "2026-02", value: null },
      { date: "2026-03", value: 15 },
    ]);
  });
});
