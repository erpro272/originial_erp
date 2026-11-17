import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// answers run real ERP tools: under a full parallel run they can take longer than the default 5 s
test.use({ actionTimeout: 15_000 });
const SLOW = { timeout: 15_000 };

test.describe.configure({ timeout: 60_000 });

test("AI Assistant: open full screen from the top bar, ask, see live steps + widgets + context, then clean up", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/orders");
  await page.getByRole("link", { name: "AI Assistant" }).click();
  await expect(page).toHaveURL(/\/assistant$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "AI Assistant" }),
  ).toBeVisible(SLOW);
  await expect(page.getByRole("region", { name: "Quick prompts" })).toBeVisible(
    SLOW,
  );

  await page
    .getByLabel("Message")
    .fill("Is CNC 01 busy tomorrow, and why is ORD-1041 delayed?");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/assistant\?c=/);
  const answer = page.getByRole("article", { name: "Assistant answer" }).last();
  await expect(answer.getByText(/CNC 01 – /).first()).toBeVisible(SLOW);
  await expect(answer.getByText("ORD-1041 – Delay analysis")).toBeVisible(SLOW);
  await expect(answer.getByRole("list", { name: "Steps" })).toContainText(
    "Checking CNC 01 schedule",
  );
  await expect(
    page.getByRole("region", { name: "CNC 01 context" }),
  ).toContainText("Daily capacity");
  await expect(
    page.getByRole("region", { name: "ORD-1041 context" }),
  ).toContainText("Tata Motors");
  const title = "Is CNC 01 busy tomorrow, and why is ORD-1041 delayed?";
  await expect(
    page
      .getByRole("navigation", { name: "Conversation history" })
      .getByText(title)
      .first(),
  ).toBeVisible(SLOW);

  // a follow-up from the quick prompts, in the same conversation
  await page
    .getByRole("region", { name: "Quick prompts" })
    .getByRole("button", { name: "Which orders are at risk of delay?" })
    .click();
  await expect(
    page.getByRole("article", { name: "Assistant answer" }),
  ).toHaveCount(2);
  await expect(
    page
      .getByRole("article", { name: "Assistant answer" })
      .last()
      .getByText("Orders at risk", { exact: true }),
  ).toBeVisible(SLOW);

  // related record opens the source; the assistant comes back from history
  const url = page.url();
  await page
    .getByRole("article", { name: "Assistant answer" })
    .first()
    .getByRole("link", { name: /ORD-1041/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/orders\?q=ORD-1041/);
  await expect(
    page.getByRole("cell", { name: "ORD-1041" }).first(),
  ).toBeVisible(SLOW);
  await page.goto(url);
  await expect(
    page.getByRole("article", { name: "Assistant answer" }),
  ).toHaveCount(2);

  // clean up (rerunnable), and × goes back
  await page.getByRole("button", { name: "Clear conversation" }).click();
  await expect(page).toHaveURL(/\/assistant$/);
  await expect(
    page.getByRole("heading", { name: "How can I help with your operations?" }),
  ).toBeVisible(SLOW);
});

test("AI Assistant answers within the role's access", async ({ page }) => {
  await signIn(page, "accountant@demo.example");
  await page.getByRole("link", { name: "AI Assistant" }).click();
  await page.getByLabel("Message").fill("Is CNC 01 busy tomorrow?");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("article", { name: "Assistant answer" }),
  ).toContainText("doesn't have access");
  await page.getByRole("button", { name: "Clear conversation" }).click();
});
