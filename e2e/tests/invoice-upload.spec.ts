import path from "node:path";
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

const SAMPLES = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../samples/invoices",
);

test("upload → verify (QR cross-check, highlight, warning) → match → save", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/orders/customers");
  await page.getByRole("button", { name: /Upload invoice/ }).click();
  await page
    .getByLabel("Choose invoice files")
    .setInputFiles(path.join(SAMPLES, "einvoice_qr.pdf"));
  await page.getByRole("button", { name: "Upload 1 file" }).click();
  await page.getByRole("link", { name: "Review →" }).click({ timeout: 30_000 });

  await expect(
    page.getByText("✓ E-invoice QR matches the invoice"),
  ).toBeVisible();
  await expect(page.getByText("Matched to Bajaj Auto by GSTIN.")).toBeVisible();

  // Clicking a field highlights where it was read on the original.
  await page.getByLabel("Grand total / invoice value").click();
  await expect(page.getByTestId("highlight")).toBeVisible();

  // Change the number and IRN (unique per run, so reruns aren't duplicates): the QR no
  // longer agrees -> warnings to accept.
  const run = Date.now().toString(36);
  const number = `DMC/26-27/E2E-${run}`;
  await page.getByLabel("Invoice number").fill(number);
  await page.getByLabel("IRN").fill(run.padEnd(64, "0"));
  await expect(
    page
      .getByText(/Invoice number on the invoice doesn't match the QR code/)
      .first(),
  ).toBeVisible();
  const save = page.getByRole("button", { name: "Save invoice" });
  await expect(save).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /I've checked all \d+ warnings/ })
    .check();
  // On reruns the same customer/date/total was saved before: confirm it's not a duplicate.
  const dupConfirm = page.getByRole("checkbox", {
    name: /Possible duplicate .* Save anyway/,
  });
  if (await dupConfirm.isVisible()) await dupConfirm.check();
  await expect(page.getByText("Ready to save.")).toBeVisible();
  await save.click();

  await expect(page.getByRole("heading", { name: /Bajaj Auto/ })).toBeVisible();
  await expect(page.getByText(number)).toBeVisible();
});

test("a file that isn't an invoice type is refused at upload", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/orders/customers/imports");
  await page.getByRole("button", { name: /Upload invoice/ }).click();
  await page.getByLabel("Choose invoice files").setInputFiles({
    name: "notes.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not really a pdf"),
  });
  await page.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(
    page.getByText("Only JPG, PNG, HEIC and PDF files are supported."),
  ).toBeVisible();
});
