import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

/** Big elements whose background is still light (a missed `bg-white` etc.). Small dots / chips and the deliberate
 * inverse pieces (dark-mode buttons and selected chips are light on purpose) are ignored. */
async function lightPanels(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 60) continue;
      const m = getComputedStyle(el).backgroundColor.match(
        /rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?/,
      );
      if (!m || (m[4] !== undefined && +m[4] < 0.5)) continue;
      const lum = (0.2126 * +m[1]! + 0.7152 * +m[2]! + 0.0722 * +m[3]!) / 255;
      if (lum > 0.6)
        out.push(`${el.tagName} ${String(el.className).slice(0, 80)}`);
    }
    return out;
  });
}

const PAGES = [
  "/orders",
  "/orders/customers",
  "/planning",
  "/purchasing",
  "/purchasing/purchase",
  "/purchasing/suppliers",
  "/billing",
  "/billing/ebill",
  "/production",
  "/dashboard",
  "/assistant",
];

test("dark mode from the top bar covers every module, is remembered, and switches back", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page, "owner@demo.example");
  const html = page.locator("html");
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await page.getByRole("menuitem", { name: /Dark/ }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");

  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(html).toHaveAttribute("data-theme", "dark"); // kept across pages and reloads
    expect(await lightPanels(page), path).toEqual([]);
  }
  // dialogs too
  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await lightPanels(page), "new order dialog").toEqual([]);
  await page.keyboard.press("Escape");

  // back to following the device (light here)
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await page.getByRole("menuitem", { name: /System/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveAttribute("data-theme", "dark"); // follows the device live
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html).toHaveAttribute("data-theme", "light");
});
