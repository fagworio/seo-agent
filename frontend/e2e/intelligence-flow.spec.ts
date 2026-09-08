import { test, expect, type Page } from "@playwright/test";

const USER = {
  id: 1, email: "admin@x.com", name: "Admin", roles: ["admin"],
  permissions: ["dashboard.read", "opportunity.read", "opportunity.review",
                "opportunity.review", "experiment.read", "pages.read", "agent.run"],
  is_mfa_enabled: false,
};

const V2 = {
  topic_authority: { score: 87, label: "muito_alto" },
  query_rankability: { score: 84, label: "alto" },
  headroom: { score: 96 },
  opportunity: { score: 91, label: "forte" },
  confidence: { score: 0.89, label: "high" },
};

async function mockApi(page: Page) {
  // cookie de sessão + /me mockado (o middleware só verifica a existência do cookie)
  await page.context().addCookies([{ name: "seo_session", value: "design-check", url: "http://127.0.0.1:3000" }]);
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf", user: USER }) }));
  await page.route("**/api/v1/work-items*", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ work_items: [{
    id: "checklist:1", source: "checklist", type: "title_meta", status: "pending",
    url: "https://x.com/a/", title: "Dragon Ball Daima: temporada 2", score: 0.9,
    recommendation: "Expandir conteúdo", evidence: "CTR baixo", action_class: "safe_fix",
    risk: "low", rollback_available: true, decision_type: "title_meta",
    gsc_metrics: {}, ga4_metrics: {}, measurement_state: "not_measurable",
    rankability_v2: V2, lifecycle: "new",
  }] }) }));
  await page.route("**/api/v1/dashboard/today*", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ today: { needs_attention: 1, critical_findings: 0, safe_fixes: 1, organic_summary: null, recent_runs: [], top_opportunities: [], integration_warnings: [], google_data: { data_status: "available", connection_configured: false }, search_trend: [], top_searches: [], revalidations: [], improvement_summary: {} } }) }));
}

test("Caixa -> Drawer mostra a Inteligência V2 cruzada (persistida)", async ({ page }) => {
  await mockApi(page);
  await page.goto("/work");
  // linha do item (badge Oport V2 presente = análise V2 integrada)
  await expect(page.getByText(/Oport V2 91/).first()).toBeVisible();
  await page.getByRole("button", { name: /Dragon Ball Daima/i }).first().click();
  // drawer com o bloco de inteligência (scores V2 do backend renderizados)
  await expect(page.getByRole("heading", { name: "Inteligência (V2)" })).toBeVisible();
  await expect(page.getByText("Rankability")).toBeVisible();
  await expect(page.getByText("Topic Authority")).toBeVisible();
});

test("Página -> Summary mostra a Inteligência V2 da página", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/v1/pages/history*", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    url: "https://x.com/a/",
    history: [{ ts: "2026-02-01", source: "audit", linked_action: "", status_code: 200, title: "Dragon Ball Daima", meta_robots: "", canonical: "", cwv: null, gsc: { position: 11.4, clicks: 3500 }, content_hash: "h" }],
    intelligence: { index_state: "indexed", metrics: { position: 11.4, clicks: 3500, impressions: 127000, ctr: 0.0275 }, rankability_v2: { topic_authority: { score: 87, label: "muito_alto" }, headroom: { score: 96 }, opportunity: { score: 91, label: "forte" }, confidence: { score: 0.89, label: "high" } }, search: { summary: { clicks: 3500, impressions: 127000, avg_position: 11.4, impr_delta_pct: 31 }, distribution: { top3: 1, top10: 2, top20: 3, top50: 4, rest: 5 }, queries: [] }, semantic: { coverage: 0.74, components: { entity: 0.92, title: 1.0, body: 0.82 }, covered: ["goku"], gaps: ["temporada 2"] } },
  }) }));
  await page.goto("/pages/https%3A%2F%2Fx.com%2Fa%2F");
  await expect(page.getByText("Inteligência desta página (V2)")).toBeVisible();
  await expect(page.getByText("Topic Authority")).toBeVisible();
});
