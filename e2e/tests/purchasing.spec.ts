import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("Purchasing inventory: statuses, raise a PO, owner approves, then cancel (rerunnable)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/purchasing");
  await expect(
    page.getByRole("heading", { level: 1, name: "Purchasing" }),
  ).toBeVisible();
  for (const k of ["Total SKUs", "Below reorder", "On order", "Stock value"])
    await expect(
      page.locator("dl").getByText(k, { exact: true }),
    ).toBeVisible();
  await expect(page.getByText("Needs attention")).toBeVisible();
  await expect(page.getByText("Raw material stock & PO status")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Open purchase orders" }),
  ).toBeVisible();

  // raise a small PO for boron steel wire (adequate stock: no effect on the demo's shortages)
  await page.getByRole("button", { name: "+ Raise PO" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Material")
    .selectOption({ label: "BSW · Boron steel wire" });
  await dialog.getByLabel("Supplier").fill("E2E Test Supplier");
  await dialog.getByLabel(/Quantity/).fill("0.01");
  await dialog.getByRole("button", { name: "Raise PO" }).click();
  const toast = page.getByText(/PO-\d{4} raised/).first();
  await expect(toast).toBeVisible();
  const number = (await toast.innerText()).match(/PO-\d{4}/)![0];
  const row = page.getByTestId(`po-${number}`);
  await expect(row).toContainText("Pending approval");

  // the owner approves: ordered (counts as on order)
  await row.getByRole("button", { name: "Approve PO" }).click();
  await expect(row).toContainText("PO sent");

  // cancel it so reruns keep the demo the same
  await row.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("dialog").getByLabel("Reason").fill("e2e test PO");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel PO" })
    .click();
  await expect(page.getByTestId(`po-${number}`)).toHaveCount(0); // only open POs are listed

  // the third tab is live too
  await page.getByRole("link", { name: "Supplier Comparison" }).click();
  await expect(
    page.getByText("Supplier scorecard & price benchmark"),
  ).toBeVisible();
});

test("Raw Material Purchase: new PO, approve, gate entry, QC, timeline, cancel (rerunnable)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/purchasing/purchase");
  for (const k of ["Open POs", "Pending approval", "In transit", "Open spend"])
    await expect(
      page.locator("dl").getByText(k, { exact: true }),
    ).toBeVisible();
  await expect(page.getByText("All purchase orders")).toBeVisible();

  // + New PO (tiny quantity of boron steel wire: no effect on the demo)
  await page.getByRole("button", { name: "+ New PO" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Material")
    .selectOption({ label: "BSW · Boron steel wire" });
  await dialog.getByLabel("Supplier").fill("E2E Test Supplier");
  await dialog.getByLabel(/Quantity/).fill("0.01");
  await dialog.getByRole("button", { name: "Raise PO" }).click();
  const toast = page.getByText(/PO-\d{4} raised/).first();
  await expect(toast).toBeVisible();
  const number = (await toast.innerText()).match(/PO-\d{4}/)![0];

  // it needs the owner: a card with Approve PO
  const card = page.getByTestId(`card-${number}`);
  await expect(card).toContainText("Action required");
  await card.getByRole("button", { name: "Approve PO" }).click();
  await expect(page.getByTestId(`card-${number}`)).toHaveCount(0);

  // open it: gate entry, then QC rejects it all (stock unchanged), timeline shows every step
  await page.getByRole("table").getByText(number, { exact: true }).click();
  let win = page.getByRole("dialog");
  await expect(
    win.getByText("Approved by the owner · PO sent to the supplier"),
  ).toBeVisible();
  await win.getByRole("button", { name: "Gate entry" }).click();
  let step = page.getByRole("dialog");
  await step.getByLabel("Challan / vehicle no.").fill("E2E-CH-1");
  await step.getByRole("button", { name: "Log gate entry" }).click();
  win = page.getByRole("dialog");
  await expect(win.getByText(/Gate entry · 0.01 t · E2E-CH-1/)).toBeVisible();
  await win.getByRole("button", { name: "QC" }).click();
  step = page.getByRole("dialog");
  await step.getByLabel(/Accepted/).fill("0");
  await step.getByLabel(/Rejected/).fill("0.01");
  await step.getByLabel("Why rejected").fill("e2e test: wrong grade");
  await step.getByRole("button", { name: "Save QC" }).click();
  win = page.getByRole("dialog");
  await expect(
    win.getByText(/QC · 0 t accepted into stock · 0.01 t rejected/),
  ).toBeVisible();

  // cancel it so reruns keep the demo the same
  await win.getByRole("button", { name: "Cancel PO" }).click();
  step = page.getByRole("dialog");
  await step.getByLabel("Reason").fill("e2e test PO");
  await step.getByRole("button", { name: "Cancel PO" }).click();
  await expect(
    page.getByRole("dialog").getByText("Cancelled: e2e test PO"),
  ).toBeVisible();
});

test("Supplier comparison: recommended vendors, compare, supplier history, quote request and reply", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/purchasing/suppliers");
  for (const k of [
    "Open/Active vendors",
    "Avg on-time",
    "Avg lead time",
    "Saved (30d)",
  ])
    await expect(
      page.locator("dl").getByText(k, { exact: true }),
    ).toBeVisible();
  await expect(
    page.getByText("Supplier scorecard & price benchmark"),
  ).toBeVisible();
  const cards = page.getByRole("region", { name: "Top recommended vendors" });
  await expect(cards.getByText(/Best overall · \d/)).toBeVisible();

  // compare the suppliers of the recommended material side by side
  await cards.getByRole("button", { name: "Compare" }).first().click();
  const cmp = page.getByRole("dialog");
  await expect(cmp.getByText("Overall score")).toBeVisible();
  await expect(cmp.getByText("Defect rate")).toBeVisible();
  await page.keyboard.press("Escape");

  // a supplier's history: deliveries on time or late, QC
  await page.getByRole("table").getByText("Tata Steel BSL").first().click();
  const sup = page.getByRole("dialog");
  await expect(sup.getByRole("heading", { name: "Deliveries" })).toBeVisible();
  await expect(sup.getByText(/On time|Late/).first()).toBeVisible();
  await page.keyboard.press("Escape");

  // ask a supplier for a quote and record the reply (bought-out tie rod kits; one test supplier)
  await page.getByRole("button", { name: "+ Request Quote" }).click();
  const req = page.getByRole("dialog");
  await req
    .getByLabel("Material")
    .selectOption({ label: "TRK · Tie rod kits (bought-out)" });
  await req.getByLabel(/Other suppliers/).fill("E2E Quote Supplier");
  await req.getByRole("button", { name: "Request quotes" }).click();
  await expect(
    page.getByText(/Quote requested from 1 supplier/).first(),
  ).toBeVisible();
  const quote = page.getByTestId("quote-E2E Quote Supplier-TRK").first();
  await quote.getByRole("button", { name: "Record reply" }).click();
  const reply = page.getByRole("dialog");
  await reply.getByLabel(/Rate per sets/).fill("150");
  await reply.getByLabel(/Lead time/).fill("6");
  await reply.getByRole("button", { name: "Save quote" }).click();
  await expect(
    page.getByText("Quote from E2E Quote Supplier saved").first(),
  ).toBeVisible();
  await page
    .getByLabel("Material")
    .selectOption({ label: "Tie rod kits (bought-out)" });
  await expect(
    page.getByRole("table").getByRole("row", { name: /E2E Quote Supplier/ }),
  ).toContainText("₹150 / sets");
});
