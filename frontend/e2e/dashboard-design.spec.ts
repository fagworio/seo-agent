import { test, expect, type Page } from "@playwright/test";

const permissions = ["pages.read", "opportunity.read", "opportunity.review", "technical.read", "editorial.read", "editorial.review", "editorial.publish_confirm"];

async function authenticated(page: Page) {
  await page.context().addCookies([{ name: "seo_session", value: "design-check", url: "http://127.0.0.1:3000" }]);
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf", user: { permissions } }) }));
  await page.route("**/api/v1/pages**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pages: Array.from({ length: 25 }, (_, i) => ({ url: `https://site.test/post-${i}`, title: `Página ${i}`, health: "ok", index_state: "indexed", metrics: { position: 4.2, clicks: i, impressions: 100, ctr: .02 } })) }) }));
  await page.route("**/api/v1/work-items**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ work_items: Array.from({ length: 25 }, (_, i) => ({ id: `item-${i}`, title: `Decisão ${i}`, source: "checklist", status: "pending", score: i, action_class: "approval_required", url: "https://site.test" })) }) }));
  await page.route("**/api/v1/findings**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ findings: [] }) }));
  await page.route("**/api/v1/actions**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ corrections: [{ fingerprint: "fix-1", rule_id: "title_opportunity", label: "Oportunidade de título", url: "https://site.test/post", status: "executed", before: {}, after: {}, rollback: {}, executed_at: null }] }) }));
  await page.route("**/api/v1/editorial**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: Array.from({ length: 8 }, (_, i) => ({ id: `backlog:${i}`, type: "supporting-post", title: `Pauta ${i}`, intent: "intenção", evidence: "evidência", related_urls: [], recommendation: "recomendação", duplication_risk: "baixo", score: i, status: "proposed", published_url: "", responsible: "Editor" })) }) }));
  await page.route("**/api/v1/dashboard/today**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ today: { needs_attention: 12, critical_findings: 2, safe_fixes: 1, organic_summary: { clicks: 40, impressions: 1500, avg_position: 6.2, pages: 20 }, recent_runs: [], top_opportunities: [], integration_warnings: [], google_data: { data_status: "available", connection_configured: true, gsc_window_start: "2026-08-03", gsc_window_end: "2026-08-31", gsc_rows: 921, ga4_rows: 1098, ga4_window_end: "2026-08-31", ga4_collected_at: "2026-09-01", opportunities_total: 20, opportunities_with_google: 8, opportunities_without_google: 12 }, search_trend: [{ window_start: "2026-08-03", window_end: "2026-08-31", clicks: 40, impressions: 1500, ctr: .0267, position: 6.2, pages: 20, queries: 120 }], top_searches: [{ query: "idade do gojo", intent: "informational", clicks: 8, impressions: 500, ctr: .016, position: 5.2, pages: 1, window_start: "2026-08-03", window_end: "2026-08-31" }], revalidations: [{ id: 1, keyword: "idade do gojo", opportunity_type: "title_meta", url: "https://site.test/gojo", implemented_action: "novo título", implemented_at: "2026-09-01", due_at: "2026-09-08", elapsed_days: 2, state: "waiting_7d", baseline_status: "available", latest_google_window_end: "2026-08-31", verdict: "" }], improvement_summary: { implemented: 1, measured: 0, improved: 0, neutral: 0, worsened: 0, insufficient_data: 0, waiting_7d: 1, waiting_google: 0, ready: 0 } } }) }));
  await page.route("**/api/v1/experiments**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ experiments: [{ id: 1, keyword: "idade do gojo", opportunity_type: "title_meta", url: "https://site.test/gojo", implemented_action: "reescrever título", implemented_at: "2026-09-01", baseline: { gsc: { clicks: 5, impressions: 500, ctr: .01, position: 7 } }, current: {}, delta: {}, forecast: { expected_ctr: .02, realistic_clicks: 10, gap_clicks: 5 }, latest_result_window: "", revalidation: { state: "waiting_7d", due_at: "2026-09-08", baseline_status: "available", latest_google_window_end: "2026-08-31" }, verdict: null, windows: { "7d": false, "28d": false, "56d": false, "90d": false }, measurement_state: "waiting_data" }] }) }));
}

test("dashboard pagination and editorial pipeline remain usable", async ({ page }, testInfo) => {
  await authenticated(page);
  await page.goto("/pages");
  await expect(page.getByRole("heading", { name: "Páginas" })).toBeVisible();
  await expect(page.getByText("1–20 de 25 páginas carregadas")).toBeVisible();
  await page.getByRole("button", { name: "Próxima" }).click();
  await expect(page.getByText("Página 24")).toBeVisible();
  await page.goto("/work");
  await expect(page.getByRole("heading", { name: "Caixa de trabalho" })).toBeVisible();
  await expect(page.getByText("1–10 de 25 decisões")).toBeVisible();
  await page.goto("/editorial");
  await expect(page.getByRole("heading", { name: "Pipeline editorial" })).toBeVisible();
  await expect(page.getByText("Discovery & revisão")).toBeVisible();
  await expect(page.getByText("1–6 de 8 itens")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("editorial-desktop.png"), fullPage: true });
});

test("technical corrections use friendly labels instead of rule identifiers", async ({ page }) => {
  await authenticated(page);
  await page.goto("/technical");
  await page.getByRole("button", { name: /Correções disponíveis/ }).click();
  await expect(page.getByText("Oportunidade de título")).toBeVisible();
  await expect(page.getByText("title_opportunity", { exact: true })).toHaveCount(0);
});

test("mobile editorial keeps the primary decision surface reachable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authenticated(page);
  await page.goto("/editorial");
  await page.getByRole("button", { name: "Pauta 0" }).click();
  await expect(page.getByRole("dialog", { name: "Decisão editorial" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Aprovar" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("editorial-mobile.png"), fullPage: true });
});

test("decision drawer explains evidence, potential and link direction", async ({ page }, testInfo) => {
  await authenticated(page);
  await page.route("**/api/v1/work-items**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ work_items: [{
      id: "interlink:1", source: "interlink", type: "internal_link", status: "proposed",
      title: "https://site.test/origem → https://site.test/destino", url: "https://site.test/destino",
      score: .72, action_class: "approval_required", decision_type: "internal_link",
      evidence: "As duas páginas compartilham o mesmo tópico.", recommendation: "Usar âncora descritiva.",
      gsc_metrics: { has_queries: true, impressions: 1200, clicks: 38, position: 7.4 },
      ga4_metrics: { measurement_status: "available", sessions: 90, engagement_rate: .64, key_events: 4 },
      top_queries: [{ query: "consulta principal", impressions: 800, clicks: 24, ctr: .03, position: 6.8 }],
      link_context: { source_url: "https://site.test/origem", target_url: "https://site.test/destino", source_title: "Página de origem", target_title: "Guia completo do assunto", suggested_anchor: "guia completo", shared_terms: ["guia", "assunto"], source_excerpt: "Veja o assunto explicado nesta introdução.", insertion_instruction: "Vincule a expressão guia completo neste parágrafo.", confidence: "medium", relevance: "moderate", google_benefits: ["cria um caminho rastreável"], site_benefits: ["oferece aprofundamento"], verification_steps: ["confirmar no recrawl"], target_inbound_links: 2, source_outbound_links: 7 },
      data_freshness: { gsc_window_start: "2026-08-01" }, measurement_state: "proposed",
    }] }),
  }));
  await page.goto("/work");
  await page.getByRole("button", { name: "Link interno a adicionar" }).click();
  await expect(page.getByRole("heading", { name: "Evidência atual" })).toBeVisible();
  await expect(page.getByText("Página de origem")).toBeVisible();
  await expect(page.getByText("Página para onde o usuário será levado")).toBeVisible();
  await expect(page.getByText("“guia completo”")).toBeVisible();
  await expect(page.getByText("Como ajuda o Google")).toBeVisible();
  await expect(page.getByText(/Impacto qualitativo/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("decision-drawer.png"), fullPage: true });
});

test("title review shows the current title before the recommended change", async ({ page }, testInfo) => {
  await authenticated(page);
  await page.route("**/api/v1/work-items**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ work_items: [{
      id: "checklist:title-1", source: "checklist", type: "title_opportunity",
      status: "pending", url: "https://site.test/jujutsu-kaisen",
      title: "Jujutsu Kaisen: idade de cada personagem principal",
      recommendation: "Reescrever título e meta description com as consultas reais",
      evidence: "CTR abaixo do esperado", decision_type: "title_meta",
      action_class: "approval_required", score: .8,
    }] }),
  }));
  await page.goto("/work?source=checklist");
  const row = page.getByRole("row").filter({ hasText: "Jujutsu Kaisen: idade de cada personagem principal" });
  await expect(row.getByText("Título a revisar")).toBeVisible();
  await expect(row.getByText("Reescrever título e meta description com as consultas reais")).toBeVisible();
  await row.getByRole("button").click();
  const dialog = page.getByRole("dialog", { name: "Decisão de melhoria" });
  await expect(dialog.getByRole("heading", { name: "Jujutsu Kaisen: idade de cada personagem principal" })).toBeVisible();
  await expect(dialog.getByText("Reescrever título e meta description com as consultas reais")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("title-review-hierarchy.png"), fullPage: true });
});

test("home exposes real Google searches and revalidation state", async ({ page }, testInfo) => {
  await authenticated(page);
  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "idade do gojo" })).toBeVisible();
  await expect(page.getByText("Somente uma janela está disponível; ainda não há base para afirmar tendência.")).toBeVisible();
  await expect(page.getByText("Aguardando 7 dias", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("today-google-data.png"), fullPage: true });
});

test("home supports the previous dashboard response during an API restart", async ({ page }) => {
  await authenticated(page);
  await page.route("**/api/v1/dashboard/today**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ today: {
      needs_attention: 3,
      critical_findings: 1,
      safe_fixes: 0,
      organic_summary: null,
      recent_runs: [],
      top_opportunities: [],
      integration_warnings: [],
    } }),
  }));
  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "Hoje" })).toBeVisible();
  await expect(page.getByText("Dados GSC ausentes")).toBeVisible();
  await expect(page.getByText("Nenhuma janela GSC armazenada. O sistema não pode calcular tendência.")).toBeVisible();
});

test("improvements separates forecast from measured result", async ({ page }, testInfo) => {
  await authenticated(page);
  await page.goto("/improvements");
  await expect(page.getByRole("heading", { name: "Melhorias" })).toBeVisible();
  await expect(page.getByText("+10 cliques")).toBeVisible();
  await expect(page.getByText("Aguardando medição")).toBeVisible();
  await page.getByRole("button", { name: "Título e meta description" }).click();
  await expect(page.getByRole("heading", { name: "Previsão" })).toBeVisible();
  await expect(page.getByText("Previsão é cenário, não resultado garantido.")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("improvements-detail.png"), fullPage: true });
});

test("improvements supports experiments created by the previous API contract", async ({ page }) => {
  await authenticated(page);
  await page.route("**/api/v1/experiments**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ experiments: [{
      id: 7,
      keyword: "consulta antiga",
      opportunity_type: "title_meta",
      url: "https://site.test/antiga",
      implemented_action: "reescrever título",
      implemented_at: "2026-08-01",
      baseline: {},
      verdict: null,
      windows: { "28d": false },
      measurement_state: "waiting_data",
    }] }),
  }));
  await page.goto("/improvements");
  await expect(page.getByText("Sem previsão")).toBeVisible();
  await page.getByRole("button", { name: "Título e meta description" }).click();
  await expect(page.getByRole("heading", { name: "Revalidação" })).toBeVisible();
  await expect(page.getByText("Não agendada")).toBeVisible();
});
