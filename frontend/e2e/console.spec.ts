import { expect, type Page, test } from "@playwright/test";

// Demo accounts from .env.example (local synthetic demo only). Override for other setups.
const PASSWORDS = {
  viewer: process.env.E2E_VIEWER_PASSWORD ?? "viewer-demo-pass-2026",
  secadmin: process.env.E2E_ADMIN_PASSWORD ?? "secadmin-demo-pass-2026",
};

// Signing in on a deep link lands on that page (the twin's 3D view is skipped when not needed).
async function signIn(page: Page, username: keyof typeof PASSWORDS, path = "/"): Promise<void> {
  await page.goto(path);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORDS[username]);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
}

test("rejects a wrong password without revealing which part was wrong", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("secadmin");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});

test("the live twin maps every backend asset and shows backend state on selection", async ({ page }) => {
  await signIn(page, "secadmin");
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  // The GLB is loaded and every physical asset's node was found by its backend id.
  await expect(page.getByText("Twin mapping verified · 21 assets")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("list", { name: "Assets" }).getByRole("button", { name: /ICU-PUMP-01/ }).click();
  await expect(page.getByRole("heading", { name: "Infusion Pump Representation - Bay 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close inspector" })).toBeVisible();
});

test("a viewer can look but cannot run attack scenarios", async ({ page }) => {
  await signIn(page, "viewer", "/scenarios");
  await expect(page.getByRole("heading", { name: "Scenario console" })).toBeVisible();
  const runButtons = page.getByRole("button", { name: "Run" });
  await expect(runButtons.first()).toBeVisible();
  for (const button of await runButtons.all()) await expect(button).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reset baseline" })).toHaveCount(0);
});

test("scenario A runs through the real pipeline and meets every expectation", async ({ page }) => {
  await signIn(page, "secadmin", "/scenarios");
  await expect(page.getByRole("heading", { name: "Scenario console" })).toBeVisible();

  // Start from the known baseline (a new epoch; audit history is kept).
  await page.getByRole("button", { name: "Reset baseline" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Justification/).fill("E2E test: start from the known baseline");
  await dialog.getByRole("button", { name: "Reset baseline" }).click();
  await expect(page.getByText(/Baseline restored \(epoch \d+\)/)).toBeVisible();

  const card = page.locator("article").filter({ hasText: "Replayed medical telemetry" });
  await card.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("heading", { name: "Result: Scenario A" })).toBeVisible();
  // Expectations are evaluated server-side against persisted state; all of them must hold.
  await expect(page.getByText(/^Run #\d+ · .* · (\d+)\/\1 expectations met$/)).toBeVisible();
  const expectations = page.getByRole("region", { name: "Expectations, evaluated against persisted state" });
  await expect(expectations.locator('[aria-label="Met"]').first()).toBeVisible();
  await expect(expectations.locator('[aria-label="Not met"]')).toHaveCount(0);
});
