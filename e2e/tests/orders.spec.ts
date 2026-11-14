import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signIn(page, "owner@demo.example", /Demo Manufacturing/);
  await page.goto("/orders");
  await expect(page.getByText("All orders received")).toBeVisible();
});

test("KPIs, needs-attention cards and the Raise PO action come from the API", async ({ page }) => {
  const kpis = page.locator("dl").first();
  await expect(kpis).toContainText("Open orders");
  await expect(kpis).toContainText("Ship in 7 days");
  const cards = page.getByRole("button", { name: /^Open ORD-/ });
  await expect(cards).toHaveCount(3);
  const tata = page.getByRole("button", { name: "Open ORD-1041" });
  await expect(tata).toContainText("Steel wire rod short · 2.4 t");
  await tata.getByRole("link", { name: "Raise PO" }).click();
  await expect(page).toHaveURL(/\/purchasing\?material=WR8/);
});

test("filter by status, switch to past orders, and save a view", async ({ page }) => {
  const table = page.getByTestId("table-orders");
  await page.getByRole("button", { name: "Status filter" }).click();
  await page.getByRole("checkbox", { name: "Material short" }).check();
  await page.keyboard.press("Escape");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table).toContainText("ORD-1041");

  await page.getByRole("button", { name: "Saved views" }).click();
  await page.getByRole("menuitem", { name: /Save current filters/ }).click();
  const name = `Short ${Date.now().toString(36)}`;
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Save view" }).click();
  await expect(page.getByRole("button", { name: "Saved views" })).toContainText(name);

  await page.reload();
  await page.getByRole("button", { name: "Saved views" }).click();
  await page.getByRole("menuitem", { name }).click();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Saved views" }).click();
  await page.getByRole("menuitem", { name: "Delete this view" }).click();
  await page.getByRole("button", { name: "Saved views" }).click();
  await page.getByRole("menuitem", { name: "Clear all filters" }).click();

  await page.getByRole("tab", { name: "Past" }).click();
  await expect(table).toContainText("Shipped");
  await expect(table).not.toContainText("ORD-1041");
});

test("create, edit and cancel an order", async ({ page }) => {
  await page.getByRole("button", { name: "+ New order" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Customer").selectOption({ label: "JCB India" });
  await dialog.getByLabel("Product").selectOption({ label: "M16 hex nuts (M16-HN)" });
  await dialog.getByLabel("Quantity (pcs)").fill("5000");
  await dialog.getByLabel("Unit price (₹)").fill("12.50");
  const ship = new Date(Date.now() + 20 * 86400_000).toISOString().slice(0, 10);
  await dialog.getByLabel("Ship date").fill(ship);
  await expect(dialog).toContainText("₹62,500");
  await dialog.getByRole("button", { name: "Create order" }).click();
  const toast = page.getByText(/^ORD-\d+ created$/).first();
  await expect(toast).toBeVisible();
  const number = (await toast.textContent())!.replace(" created", "");

  await page.getByLabel("Search orders").fill(number);
  const row = page.getByTestId("table-orders").locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("62,500");
  await row.click();
  await page.getByRole("dialog").getByLabel("Priority").selectOption("high");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(row.getByText("High")).toBeVisible();

  await row.click();
  await page.getByRole("button", { name: "Cancel order" }).click();
  await page.getByRole("dialog", { name: /Cancel ORD/ }).getByLabel("Reason").fill("Customer postponed");
  await page.getByRole("dialog", { name: /Cancel ORD/ }).getByRole("button", { name: "Cancel order" }).click();
  await expect(page.getByText(`${number} cancelled`)).toBeVisible();
  await expect(page.getByTestId("table-orders")).toContainText("No open orders match"); // gone from current orders
  await page.getByRole("tab", { name: "Past" }).click();
  await expect(page.getByTestId("table-orders")).toContainText("Cancelled");
});
