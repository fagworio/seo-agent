import { test, expect, type Page } from "@playwright/test";

const USER = {
  id: 1,
  email: "admin@x.com",
  name: "Admin",
  roles: ["admin"],
  permissions: ["dashboard.read", "opportunity.read", "opportunity.review"],
  is_mfa_enabled: true,
};

const TODAY = {
  today: {
    needs_attention: 3,
    critical_findings: 2,
    safe_fixes: 1,
    organic_summary: { clicks: 80, impressions: 1800, avg_position: 4.2, pages: 2 },
    recent_runs: [{ id: 1, agent: "hermes-seo-agent", status: "success", intent: "technical" }],
    top_opportunities: [{ id: "checklist:1", source: "checklist", title: "Melhorar title", score: 0.8, status: "pending" }],
    integration_warnings: [{ source: "gsc", data_status: "missing" }],
  },
};

async function mockApi(page: Page) {
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, requires_mfa: true, mfa_user_id: 1 }),
    }),
  );
  await page.route("**/api/v1/auth/mfa/verify", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      // cookie __Host- requer Secure; Chromium envia Secure sobre localhost
      headers: { "Set-Cookie": "__Host-seo_session=testtoken; HttpOnly; SameSite=Strict; Path=/; Secure" },
      body: JSON.stringify({ ok: true, user: USER, csrf_token: "csrf" }),
    }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ user: USER, csrf_token: "csrf" }) }),
  );
  await page.route("**/api/v1/dashboard/today**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TODAY) }),
  );
}

test("login: credenciais -> passo MFA", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@x.com");
  await page.getByLabel("Senha").fill("senha123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Verificação em duas etapas")).toBeVisible();
  await expect(page.getByPlaceholder("000000")).toBeVisible();
});

test("fluxo completo: login -> MFA -> hoje renderiza", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@x.com");
  await page.getByLabel("Senha").fill("senha123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByPlaceholder("000000").fill("123456");
  await page.getByRole("button", { name: "Confirmar" }).click();
  // após o MFA a aplicação navega para /hoje e o read model renderiza
  await expect(page.getByText("Precisa de atenção")).toBeVisible();
  await expect(page.getByText("hermes-seo-agent")).toBeVisible();
});
