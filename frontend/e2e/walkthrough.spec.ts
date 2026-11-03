// Story #136 AC5 and AC6: a manager goes from the Overview to an opportunity and reads its
// evidence, against the real API on a synthetic warehouse; axe runs on every screen, contrast
// included (a real browser lays the page out).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function noViolations(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("Overview to an opportunity and its evidence", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Data as of")).toBeVisible();
  await expect(page.getByText(/Net sales: Net_Amount_2 \(provisional\)/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Opportunities by type" })).toBeVisible();
  await noViolations(page);

  await page.getByRole("link", { name: "Dormant customer", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\?type=dormancy$/);
  await expect(page.getByText(/2 opportunities · page 1 of 1/)).toBeVisible();
  await noViolations(page);

  await page.getByRole("table").getByRole("link").first().click();
  await expect(page).toHaveURL(/\/opportunities\/[0-9a-f]{32}$/);
  const measured = page.getByRole("region", { name: /Measured fact/ });
  await expect(measured.getByText("Days since the last order")).toBeVisible();
  await expect(page.getByRole("region", { name: /Estimate/ })).toContainText("Estimate:");
  // story #138: no brief yet, so generate one (a fake Gemini answers) and read it
  const ai = page.getByRole("region", { name: /AI suggestion/ });
  await ai.getByRole("button", { name: "Generate brief" }).click();
  await expect(ai.getByText("Win back this customer")).toBeVisible();
  await expect(ai.getByText(/AI suggestion, not a measured fact/)).toBeVisible();
  await noViolations(page);

  // a number's definition opens from the keyboard
  await measured.getByRole("button", { name: /Definition of Days since the last order/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tooltip")).toContainText("Days from the customer's last order");
});
