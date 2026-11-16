import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("Receivables: cards, a customer's three dates, follow-up and commitment (rerunnable)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/billing");
  for (const k of [
    "Total Receivables",
    "Overdue",
    "Expected This Week",
    "Received This Month",
  ])
    await expect(
      page.locator("dl").getByText(k, { exact: true }),
    ).toBeVisible();
  await page.getByRole("button", { name: /^Overdue/ }).click();
  await page.getByRole("table").getByRole("row").nth(1).click();
  const drawer = page.getByRole("dialog");
  await expect(
    drawer.getByRole("region", { name: "Three dates" }),
  ).toContainText("Original due date");
  await drawer.getByRole("button", { name: "Log follow-up" }).click();
  let dialog = page.getByRole("dialog", { name: /Log follow-up/ });
  await dialog
    .getByLabel("What was said")
    .fill("e2e: called accounts, payment next week");
  await dialog.getByRole("button", { name: "Save follow-up" }).click();
  await expect(page.getByText("Follow-up logged").first()).toBeVisible();
  await drawer.getByRole("tab", { name: /Communication/ }).click();
  await expect(
    drawer.getByText("e2e: called accounts, payment next week").first(),
  ).toBeVisible();
  await drawer.getByRole("button", { name: "Update commitment" }).click();
  dialog = page.getByRole("dialog", { name: /Update commitment/ });
  const next = new Date(Date.now() + 5 * 86_400_000).toISOString().slice(0, 10);
  await dialog.getByLabel("Customer will pay by").fill(next);
  await dialog.getByLabel(/Amount/).fill("1000");
  await dialog.getByRole("button", { name: "Save promise" }).click();
  await expect(page.getByText("Commitment updated").first()).toBeVisible();
  await drawer.getByRole("tab", { name: "Commitment" }).click();
  await expect(
    drawer.getByRole("region", { name: "Three dates" }),
  ).toContainText("Promised payment date");
});

test("Payables: supplier invoice -> verify -> approve -> schedule -> execute (logged override) -> bank confirm", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/billing?mode=ap");
  await expect(page.getByText("Supplier payables")).toBeVisible();
  const number = `E2E-${Date.now()}`;
  await page.getByRole("button", { name: "+ Supplier invoice" }).click();
  let dialog = page.getByRole("dialog", { name: "Supplier invoice received" });
  const po = dialog.getByLabel("Purchase order");
  const option = po.locator("option", { hasText: "Rane Components" }).first();
  await po.selectOption({ value: (await option.getAttribute("value"))! });
  await dialog.getByLabel("Invoice number").fill(number);
  await dialog.getByLabel(/Quantity billed/).fill("1"); // well within what QC accepted
  await dialog.getByRole("button", { name: "Record invoice" }).click();
  await expect(page.getByText(`${number} recorded`).first()).toBeVisible();

  await page.getByLabel("Search suppliers").fill("Rane");
  await page.getByRole("table").getByText("Rane Components").click();
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: new RegExp(number) }).click();
  await drawer
    .getByRole("button", { name: "Verify (three-way match)" })
    .click();
  await drawer.getByRole("button", { name: "Approve payment" }).click();
  await expect(
    drawer.getByText("Approved by the owner. Accounts schedule the payment."),
  ).toBeVisible();
  await drawer.getByRole("button", { name: "Schedule payment" }).click();
  dialog = page.getByRole("dialog", { name: /Schedule payment/ });
  await dialog.getByRole("button", { name: "Schedule" }).click();
  await drawer.getByRole("tab", { name: /Payment history/ }).click();
  await drawer.getByRole("button", { name: "Execute payment" }).click();
  dialog = page.getByRole("dialog", { name: /Execute payment/ });
  await dialog.getByLabel("UTR (bank reference)").fill(`U${Date.now()}`);
  await dialog.getByRole("button", { name: "Mark sent" }).click();
  // the owner approved it, so sending it needs an override reason (segregation of duties)
  await expect(dialog.getByRole("alert")).toContainText("can't also execute");
  await dialog.getByLabel(/Override reason/).fill("e2e: accountant on leave");
  await dialog.getByRole("button", { name: "Mark sent" }).click();
  await drawer.getByRole("button", { name: "Bank confirmation" }).click();
  dialog = page.getByRole("dialog", { name: /Bank confirmation/ });
  await dialog.getByRole("button", { name: "Confirm from statement" }).click();
  await drawer.getByRole("tab", { name: "Settlement" }).click();
  await expect(
    drawer.getByText("Settled: every rupee sent and confirmed by the bank."),
  ).toBeVisible();
});

test("Invoice / E-bill: deals, drawer tabs, a provisional deal created then archived (rerunnable)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/billing/ebill");
  for (const k of [
    "Active deals",
    "Awaiting response",
    "Documents received",
    "Invoices issued",
  ])
    await expect(
      page.locator("dl").getByText(k, { exact: true }),
    ).toBeVisible();
  await page.getByLabel("Search deals").fill("ORD-1044");
  await page
    .getByRole("table")
    .getByText(/ORD-1044/)
    .first()
    .click();
  let drawer = page.getByRole("dialog");
  await expect(drawer.getByText(/No dispatch recorded yet/)).toBeVisible();
  await expect(
    drawer.getByRole("button", { name: "Generate invoice" }),
  ).toBeDisabled();
  await drawer.getByRole("tab", { name: /Documents/ }).click();
  await expect(drawer.getByText("Customer PO / sales order")).toBeVisible();
  await page.keyboard.press("Escape");

  const ref = `ENQ-E2E-${Date.now()}`;
  await page.getByRole("button", { name: "Create deal ▾" }).click();
  await page.getByRole("menuitem", { name: "Sale deal" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Customer/).fill("Hero MotoCorp");
  await dialog.getByLabel("Product").fill("Bulk fastener assortment");
  await dialog.getByLabel(/Reference/).fill(ref);
  await dialog.getByRole("button", { name: "Create deal" }).click();
  drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Provisional")).toBeVisible();
  await expect(drawer.getByText("Enquiry Received").first()).toBeVisible();
  await drawer.getByRole("button", { name: "Archive" }).click();
  await expect(drawer.getByText("Archived").first()).toBeVisible();
});
