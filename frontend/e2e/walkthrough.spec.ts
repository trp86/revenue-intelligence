// The browser walkthrough and accessibility checks (stories #136, #138, #148-#151). The real API
// serves a synthetic warehouse (e2e/make_warehouse.py) with a fake Gemini (e2e/serve_fake_ai.py).
// The tests share that server and run in this order: the keyboard pass opens the brief dialog but
// never generates; the walkthrough generates the one brief; the width pass checks every screen.
// Screenshots go to frontend/test-results/ (git-ignored) for review.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const WIDTHS = [
  { width: 1440, height: 1000 },
  { width: 1024, height: 900 },
  { width: 390, height: 900 },
];

async function noViolations(page: Page, where: string) {
  const result = await new AxeBuilder({ page }).analyze(); // every rule, colour contrast included
  expect(result.violations.map((v) => `${where}: ${v.id}: ${v.help}`)).toEqual([]);
}

/** Press Tab until the focused element has this accessible name (at most 80 presses). */
async function tabTo(page: Page, name: RegExp) {
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      // only controls count: Tab can wrap round to <body>, whose text holds every name
      if (!el || !el.matches("a, button, input, select, textarea, [role=tab], [tabindex='0']")) return "";
      return (el.getAttribute("aria-label") ?? el.innerText ?? "").trim();
    });
    if (name.test(label)) return;
  }
  throw new Error(`no focusable element named ${name} within 80 Tab presses`);
}

/** The focused element shows the 2 px focus ring from the design tokens. */
async function expectFocusRing(page: Page) {
  const outline = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement as Element);
    return { style: style.outlineStyle, width: style.outlineWidth };
  });
  expect(outline).toEqual({ style: "solid", width: "2px" });
}

async function firstOpportunityId(page: Page): Promise<string> {
  await page.goto("/opportunities");
  const href = await page.getByRole("table").getByRole("link").first().getAttribute("href");
  return href!.split("/").pop()!;
}

test("keyboard only: skip link, navigation, preview, definitions, dialog and the menu", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // the first Tab reaches the skip link, which moves focus to the main region
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  await expect(page.locator("main#main")).toBeFocused();

  // sidebar navigation to the Explorer
  await page.locator("body").focus();
  await tabTo(page, /Opportunity Explorer/);
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByText(/opportunities · page 1/)).toBeVisible();

  // a type tab, then the first row's preview, then Open details
  await tabTo(page, /^Dormant customer$/);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/type=dormancy/);
  await tabTo(page, /^Preview /);
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Preview" })).toBeVisible();
  await tabTo(page, /Open details/);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/opportunities\/[0-9a-f]{32}$/);

  // a definition opens and closes by keyboard
  await expect(page.getByRole("region", { name: "Measured fact" })).toBeVisible();
  await tabTo(page, /^Definition of Days since the last order$/);
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tooltip")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  // the Generate dialog opens by keyboard, keeps focus inside, and Escape closes it
  await tabTo(page, /^Generate brief$/);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Generate an AI brief?" });
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Generate brief" })).toBeFocused();

  // on a phone the navigation is a menu that opens and closes by keyboard
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/");
  await tabTo(page, /^Open menu$/);
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  const menu = page.getByRole("dialog");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
});

test("walkthrough: Overview, a type, the Explorer preview, Detail and an AI brief", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByText("Data as of")).toBeVisible();
  const byType = page.getByRole("region", { name: "Opportunities by type and priority" });
  await expect(byType.getByRole("img", { name: /has the most opportunities/ })).toBeVisible();
  await byType.getByRole("button", { name: "Show as table" }).click();
  await noViolations(page, "overview table view");
  await byType.getByRole("link", { name: "Dormant customer", exact: true }).click();

  await expect(page).toHaveURL(/\/opportunities\?type=dormancy$/);
  await page.getByRole("button", { name: /^Preview / }).first().click();
  const preview = page.getByRole("region", { name: "Preview" });
  await expect(preview.getByText("What happened")).toBeVisible();
  await noViolations(page, "explorer with preview");
  await preview.getByRole("link", { name: /Open details/ }).click();

  await expect(page).toHaveURL(/\/opportunities\/[0-9a-f]{32}$/);
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Dormant customer:");
  await expect(page.getByRole("region", { name: "Measured fact" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Estimate" })).toBeVisible();
  const ai = page.getByRole("region", { name: "AI suggestion" });
  await ai.getByRole("button", { name: "Generate brief" }).click();
  const confirm = page.getByRole("dialog", { name: "Generate an AI brief?" });
  await expect(confirm).toContainText("counts toward the daily limit");
  await noViolations(page, "confirm dialog");
  await confirm.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByText("AI brief generated")).toBeVisible();
  await expect(ai.getByText("Win back this customer")).toBeVisible();
  await noViolations(page, "detail with brief");
  await page.screenshot({ path: "test-results/walkthrough-brief-1440.png", fullPage: true });
});

for (const size of WIDTHS) {
  test(`every screen passes axe at ${size.width} px, with a screenshot`, async ({ page }) => {
    await page.setViewportSize(size);
    const id = await firstOpportunityId(page);
    const screens = [
      { name: "overview", path: "/", ready: "Opportunities by type and priority" },
      { name: "explorer", path: `/opportunities?selected=${id}`, ready: "Preview" },
      { name: "detail", path: `/opportunities/${id}`, ready: "AI suggestion" },
    ];
    for (const s of screens) {
      await page.goto(s.path);
      await expect(page.getByRole("region", { name: s.ready })).toBeVisible();
      await page.waitForTimeout(300); // let fonts and layout settle before the contrast check
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${s.name} at ${size.width} px scrolls sideways`).toBeLessThanOrEqual(0);
      await noViolations(page, `${s.name} at ${size.width} px`);
      await page.screenshot({ path: `test-results/${s.name}-${size.width}.png`, fullPage: true });
    }
  });
}

test("large KPI values fit their cards at every width (story #159)", async ({ page }) => {
  // the synthetic warehouse is small, so the overview answer is patched with billion-sized values
  await page.route("**/api/v1/overview", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.kpis.value_low.value = 1498167302;
    body.kpis.value_high.value = 4494501907;
    await route.fulfill({ response, json: body });
  });
  for (const size of WIDTHS) {
    await page.setViewportSize(size);
    await page.goto("/");
    await expect(page.getByText("4.49B")).toBeVisible();
    for (const name of ["Value, low estimate", "Value, high estimate"]) {
      const card = page.locator("div", { has: page.getByText(name, { exact: true }) }).filter({ has: page.locator("[data-metric]") }).last();
      const fits = await card.evaluate((el) => {
        const metric = el.querySelector("[data-metric]") as HTMLElement;
        const box = el.getBoundingClientRect();
        const inner = metric.getBoundingClientRect();
        return inner.right <= box.right && inner.height < 48; // one line, inside the card
      });
      expect(fits, `${name} at ${size.width} px`).toBe(true);
    }
    await noViolations(page, `overview with large values at ${size.width} px`);
    await page.screenshot({ path: `test-results/overview-large-values-${size.width}.png` });
  }
});

test("the Value (estimate) definition opens fully on screen at 1440 px (story #162)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/opportunities");
  await page.getByRole("button", { name: "Definition of value (estimate)" }).click();
  const tip = page.getByRole("tooltip");
  await expect(tip).toBeVisible();
  const box = (await tip.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(240);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(1440);
  // nothing covers it: the topmost element at its centre is the panel itself
  const onTop = await page.evaluate(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return !!el?.closest("[role=tooltip]");
  }, [box.x + box.width / 2, box.y + box.height / 2]);
  expect(onTop).toBe(true);
  await noViolations(page, "explorer with the value definition open");
  await page.screenshot({ path: "test-results/explorer-definition-1440.png" });
});

test("only one definition popup is open at a time; a click outside closes it (story #173)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const id = await firstOpportunityId(page);
  await page.goto(`/opportunities/${id}`);
  const measured = page.getByRole("region", { name: "Measured fact" });
  const buttons = measured.getByRole("button", { name: /^Definition of/ });
  await buttons.nth(0).click();
  await buttons.nth(1).click();
  await expect(page.getByRole("tooltip")).toHaveCount(1);
  await noViolations(page, "detail with one definition open");
  await page.getByRole("heading", { level: 1 }).click();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page.goto("/");
  const top = page.getByRole("table", { name: /^Top \d+ opportunities$/ });
  await expect(top.getByRole("button", { name: /^Definition of/ })).toHaveCount(2);
});
