import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

const headers = (page: Page) =>
  page.getByTestId("table-audit-log").locator("thead th");

test("audit log columns: hide, reorder and keep the choice after reload", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/settings/audit-log");
  const columnsBtn = page.getByRole("button", { name: /Columns \(\d+\)/ });

  // Start from defaults.
  await columnsBtn.click();
  await page.getByRole("button", { name: "Reset" }).click();
  await expect(headers(page)).toHaveText([
    "When",
    "Who",
    "Action",
    "Record",
    "Summary",
  ]);

  // Hide "Record", show "Request ID".
  await page.getByRole("checkbox", { name: "Record", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "Request ID" }).check();
  await expect(headers(page)).toHaveText([
    "When",
    "Who",
    "Action",
    "Summary",
    "Request",
  ]);

  // Drag "Summary" above "Who".
  const handle = page.getByRole("button", { name: "Reorder Summary" });
  const target = page.getByRole("button", { name: "Reorder Who" });
  const hb = (await handle.boundingBox())!;
  const tb = (await target.boundingBox())!;
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + hb.width / 2, hb.y - 10, { steps: 5 });
  await page.mouse.move(tb.x + tb.width / 2, tb.y + 2, { steps: 10 });
  await page.mouse.up();
  await expect(headers(page)).toHaveText([
    "When",
    "Summary",
    "Who",
    "Action",
    "Request",
  ]);
  await page.keyboard.press("Escape");

  // Saved per user: survives a reload.
  await page.reload();
  await expect(headers(page)).toHaveText([
    "When",
    "Summary",
    "Who",
    "Action",
    "Request",
  ]);
  await expect(page.getByRole("button", { name: "Columns (5)" })).toBeVisible();

  // Row opens the detail modal.
  await page.getByTestId("table-audit-log").locator("tbody tr").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Clean up so the test is repeatable.
  await page.getByRole("button", { name: /Columns/ }).click();
  await page.getByRole("button", { name: "Reset" }).click();
});
