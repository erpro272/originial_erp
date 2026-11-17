import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test.use({ actionTimeout: 15_000 });
const SLOW = { timeout: 15_000 };

// Applies a follow-up (adds one more note each run: rerunnable). Plan fixes are covered by pytest only: applying
// one would change the shared demo plan the planning e2e relies on.
test("AI Assistant actions: tick a suggestion, review it (re-checked), confirm: applied once, with a link", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/assistant");
  await page.getByLabel("Message").fill("What do customers owe us?");
  await page.keyboard.press("Enter");
  const card = page.getByRole("region", { name: "Recommended actions" }).last();
  await expect(card).toBeVisible(SLOW);
  await expect(card.getByRole("button", { name: "Apply" })).toBeDisabled();

  await card.getByRole("checkbox").first().check();
  await card.getByRole("button", { name: "Apply" }).click();
  const dlg = page.getByRole("dialog", { name: "Review before applying" });
  await expect(dlg.getByText(/Logs a call follow-up/)).toBeVisible(SLOW);
  const note = `e2e follow-up ${Date.now()}`;
  await dlg.getByLabel("Note (you can edit it)").fill(note);
  await dlg.getByRole("button", { name: "Confirm and apply" }).click();
  await expect(card.getByText("Applied")).toBeVisible(SLOW);
  await expect(card.getByText(note, { exact: false })).toBeVisible();

  // dismiss another one; statuses survive a reload
  await card.getByRole("button", { name: "Dismiss" }).first().click();
  await expect(card.getByText("Dismissed")).toBeVisible();
  await page.reload();
  const again = page
    .getByRole("region", { name: "Recommended actions" })
    .last();
  await expect(again.getByText("Applied")).toBeVisible(SLOW);
  await expect(again.getByText("Dismissed")).toBeVisible();

  // the note is really in Billing
  await again.getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/billing\?customer=/);
  await page
    .getByRole("dialog")
    .getByRole("tab", { name: /Communication/ })
    .click();
  await expect(page.getByRole("dialog").getByText(note).first()).toBeVisible(
    SLOW,
  );

  await page.goto("/assistant");
  await page
    .getByRole("navigation", { name: "Conversation history" })
    .getByText("What do customers owe us?")
    .first()
    .click();
  await page.getByRole("button", { name: "Clear conversation" }).click();
});
