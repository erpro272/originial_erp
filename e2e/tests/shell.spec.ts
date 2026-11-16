import { expect, test } from "@playwright/test";
import { signIn, signOut } from "./helpers";

test("sign in, visit every module, sign out", async ({ page }) => {
  await page.goto("/planning");
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, "owner@demo.example");
  // Lands back on the page they asked for.
  await expect(page).toHaveURL(/\/planning$/);

  const nav = page.getByRole("navigation", { name: "Main" });
  const modules = [
    "Orders",
    "Planning",
    "Purchasing",
    "Production",
    "Billing",
    "Finance",
    "Dashboard",
  ];
  await expect(nav.getByRole("link")).toHaveText(modules);
  for (const name of modules) {
    await nav.getByRole("link", { name }).click();
    const title = name === "Planning" ? /Order manufacturing plan/ : name;
    await expect(
      page.getByRole("heading", { level: 1, name: title }),
    ).toBeVisible();
    if (name === "Orders")
      await expect(page.getByText("All orders received")).toBeVisible();
    else if (name === "Purchasing")
      await expect(
        page.getByText("Raw material stock & PO status"),
      ).toBeVisible();
    else if (name === "Planning")
      await expect(
        page.getByRole("link", { name: "Plan history →" }),
      ).toBeVisible();
    else
      await expect(
        page.getByRole("heading", { name: "Coming soon" }),
      ).toBeVisible();
  }

  // Session survives a reload (refresh cookie).
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Dashboard" }),
  ).toBeVisible();

  await signOut(page);
  await page.goto("/orders");
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong password is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("planner@demo.example");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Email or password is incorrect.",
  );
});

test("planner cannot open the audit log", async ({ page }) => {
  await signIn(page, "planner@demo.example");
  await page.getByRole("button", { name: /Account menu/ }).click();
  await expect(page.getByRole("menuitem", { name: "Audit log" })).toHaveCount(
    0,
  );
  await page.keyboard.press("Escape");
  await page.goto("/settings/audit-log");
  await expect(
    page.getByText("You don't have access to this page"),
  ).toBeVisible();
});

test("each company sees only its own data", async ({ page }) => {
  await signIn(page, "owner@second.example");
  await expect(
    page.getByRole("button", { name: /Account menu/ }),
  ).toContainText("Second Fasteners");
  await page.getByRole("button", { name: /Account menu/ }).click();
  await expect(page.getByText("Switch company")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await page.goto("/settings/audit-log");
  const table = page.getByTestId("table-audit-log");
  await expect(table).toContainText("Second Fasteners Pvt Ltd' created");
  await expect(table).not.toContainText("Demo Manufacturing Co.' created");
});
