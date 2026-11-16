import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("Dashboard: sections, machine load detail, alerts drawer, date range in the URL", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Dashboard" })
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Operations Dashboard" }),
  ).toBeVisible();
  for (const h of [
    "Order Timeline",
    "Factory Layout",
    "Cash Flow: Invoiced vs Collected & Payables (Last 6 Months)",
    "Customer Health & Priority Orders",
    "Alerts & Updates",
  ])
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  for (const k of [
    "Overall Utilization",
    "In Progress",
    "Avg. Cycle Time",
    "Delayed Orders",
  ])
    await expect(page.getByText(k, { exact: true })).toBeVisible();

  // machine load: click a machine to see what loads it, with a way into Planning
  await page.getByRole("button", { name: /^CNC 01: current plan/ }).click();
  const m = page.getByRole("dialog", { name: /CNC 01 · machine load/ });
  await expect(m.getByText("Day by day")).toBeVisible();
  await expect(
    m.getByRole("link", { name: /schedule in Planning/ }),
  ).toBeVisible();
  await page.keyboard.press("Escape");

  // Status view of the timeline
  await page.getByRole("tab", { name: "Status View" }).first().click();
  await expect(
    page.getByRole("columnheader", { name: "Scheduled" }),
  ).toBeVisible();

  // factory layout hover card (shared with Production)
  await page.getByLabel("Packaging Area").hover();
  await expect(page.getByRole("tooltip")).toContainText("units/hr");

  // alerts: View All opens the drawer; an alert opens its source
  await page.getByRole("button", { name: /View All/ }).click();
  const sheet = page.getByRole("dialog", { name: "Alerts & Updates" });
  await expect(
    sheet.getByRole("group", { name: "Filter alerts by module" }),
  ).toBeVisible();
  await sheet
    .getByRole("link", { name: /PO-\d+ (delayed|awaiting|at the gate)/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/purchasing\/purchase\?po=/);

  // date range lives in the URL
  await page.goBack();
  await page.getByRole("button", { name: /Date range:/ }).click();
  await page.getByRole("button", { name: /^This month/ }).click();
  await expect(page).toHaveURL(/from=\d{4}-\d{2}-01&to=/);
  await expect(
    page.getByRole("heading", { name: "Order Timeline" }),
  ).toBeVisible();
});

test("Dashboard is the owner's view", async ({ page }) => {
  await signIn(page, "planner@demo.example");
  await page.goto("/dashboard");
  await expect(
    page.getByText("You don't have access to this page"),
  ).toBeVisible();
});
