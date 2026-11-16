import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("Production factory layout: hovering a station or stage shows its numbers (demo data)", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/production");
  await expect(
    page.getByRole("heading", { level: 1, name: "Factory Layout" }),
  ).toBeVisible();
  await page.getByLabel("Packaging Area").hover();
  const tip = page.getByRole("tooltip");
  await expect(tip).toContainText("Running");
  await expect(tip).toContainText("620 units/hr");
  await page.getByLabel("Cooking & Mixing Facilities").hover();
  await expect(tip).toContainText("Issue");
  await page.getByRole("tab", { name: "Status View" }).click();
  await expect(page.getByLabel("Loading")).toContainText("Maintenance");
});
