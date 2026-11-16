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
  await expect(row).toContainText("Awaiting approval");

  // the owner approves: ordered (counts as on order)
  await row.getByRole("button", { name: "Approve" }).click();
  await expect(row).toContainText("Ordered");

  // cancel it so reruns keep the demo the same
  await row.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("dialog").getByLabel("Reason").fill("e2e test PO");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel PO" })
    .click();
  await expect(page.getByTestId(`po-${number}`)).toHaveCount(0); // only open POs are listed

  // the other sections come next
  await page.getByRole("link", { name: "Supplier Comparison" }).click();
  await expect(page.getByText(/coming next/)).toBeVisible();
});
