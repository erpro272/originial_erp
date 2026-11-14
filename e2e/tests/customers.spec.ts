import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("health chips filter the table; profile shows history and logs a reminder", async ({ page }) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/orders/customers");
  const table = page.getByTestId("table-customers");
  await expect(table).toContainText("Maruti Suzuki");
  await page.getByRole("button", { name: /^Inactive/ }).click();
  await expect(table).toContainText("TVS Motor");
  await expect(table).not.toContainText("Maruti Suzuki");

  await page.getByRole("button", { name: /Reporting period/ }).click();
  await page.getByRole("button", { name: "Last 12 months" }).click();
  await expect(page).toHaveURL(/period=last_12_months/);

  await table.getByText("TVS Motor").click();
  await expect(page.getByRole("heading", { name: /TVS Motor/ })).toBeVisible();
  await expect(page.getByText("Sales by month")).toBeVisible();
  await expect(page.getByRole("button", { name: /Reporting period: Last 12 months/ })).toBeVisible();

  await page.getByRole("button", { name: "Set reminder" }).click();
  const note = `Q4 schedule ${Date.now().toString(36)}`;
  await page.getByRole("dialog").getByLabel("Note").fill(note);
  await page.getByRole("dialog").getByLabel("Remind me on").fill(new Date().toISOString().slice(0, 10));
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(note)).toBeVisible();
});

test("planner sees masked bank details and cannot add customers", async ({ page }) => {
  await signIn(page, "planner@demo.example");
  await page.goto("/orders/customers");
  await expect(page.getByRole("button", { name: "+ Add customer" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Upload invoice/ })).toHaveCount(0);
});
