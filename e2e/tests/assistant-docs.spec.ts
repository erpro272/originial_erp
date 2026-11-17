import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// answers run real ERP tools: under a full parallel run they can take longer than the default 5 s
test.use({ actionTimeout: 15_000 });
const SLOW = { timeout: 15_000 };

test.describe.configure({ timeout: 60_000 });

test("AI Assistant documents: cited answer from a policy, upload -> indexed -> quoted -> deleted (rerunnable)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/assistant");

  // a seeded policy, quoted with document + page
  await page
    .getByLabel("Message")
    .fill("What does our costing policy say about night shifts?");
  await page.keyboard.press("Enter");
  const answer = page.getByRole("article", { name: "Assistant answer" }).last();
  await expect(
    answer.getByRole("button", { name: /Costing Policy · page 1/ }),
  ).toBeVisible(SLOW);
  await expect(answer).toContainText("25%");
  await page.getByRole("button", { name: "Clear conversation" }).click();

  // upload a new SOP with a unique word, wait for the worker to index it, ask about it
  const word = `zx${Date.now()}`;
  await page.getByRole("button", { name: "Attach a document" }).click();
  const sheet = page.getByRole("dialog", { name: "Company documents" });
  await expect(
    sheet.getByText("SOP-07 CNC Machine Safety", { exact: true }),
  ).toBeVisible(SLOW);
  await sheet.getByLabel(/File/).setInputFiles({
    name: `e2e-${word}.txt`,
    mimeType: "text/plain",
    buffer: Buffer.from(
      `Forklift SOP. Forklifts reverse with the ${word} beacon switched on in the dispatch bay.`,
    ),
  });
  await sheet.getByRole("button", { name: "Upload" }).click();
  const row = sheet.getByRole("listitem").filter({ hasText: `e2e-${word}` });
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 30_000 });
  await sheet.getByRole("button", { name: "Close" }).click();

  await page
    .getByLabel("Message")
    .fill(`What does our forklift SOP say about the ${word} beacon?`);
  await page.keyboard.press("Enter");
  await expect(
    page
      .getByRole("article", { name: "Assistant answer" })
      .last()
      .getByRole("button", { name: new RegExp(`e2e-${word}`) }),
  ).toBeVisible(SLOW);

  // clean up
  await page.getByRole("button", { name: "Clear conversation" }).click();
  await page.getByRole("button", { name: "Documents" }).click();
  await sheet.getByRole("button", { name: `Delete e2e-${word}` }).click();
  await expect(sheet.getByText(`e2e-${word}`)).toHaveCount(0);
});
