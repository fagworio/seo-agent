import { test, expect, type Page } from "@playwright/test";

test("botão Sair faz logout (revoga + redireciona para /login)", async ({ page }) => {
  let logoutCalled = false;
  await page.context().addCookies([{ name: "seo_session", value: "design-check", url: "http://127.0.0.1:3000" }]);
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf", user: { email: "admin@x.com", name: "Admin", roles: ["admin"], permissions: ["dashboard.read"], is_mfa_enabled: false } }) }));
  await page.route("**/api/v1/auth/logout", (r) => { logoutCalled = true; return r.fulfill({ status: 200, contentType: "application/json", headers: { "Set-Cookie": "seo_session=; HttpOnly; Path=/; Max-Age=0" }, body: JSON.stringify({ ok: true }) }); });
  // qualquer fetch de dados (para a página renderizar o header) — devolve vazio
  await page.route("**/api/v1/dashboard/today**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ today: { needs_attention: 0, critical_findings: 0, safe_fixes: 0, organic_summary: null, recent_runs: [], top_opportunities: [], integration_warnings: [], google_data: { data_status: "missing", connection_configured: false }, search_trend: [], top_searches: [], revalidations: [], improvement_summary: {} } }) }));

  await page.goto("/today");
  const btn = page.getByRole("button", { name: /Sair/ });
  await expect(btn).toBeVisible();
  await btn.click();
  // o POST /auth/logout é assíncrono (após GET /auth/me pegar o csrf) — poll até
  // a rota ser chamada, em vez de checar o booleano imediatamente (corrida).
  await expect.poll(() => logoutCalled, { timeout: 10_000 }).toBeTruthy();
  await page.waitForURL(/login/, { timeout: 10_000 });
});
