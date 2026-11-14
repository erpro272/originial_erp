import { expect, test, type APIRequestContext } from "@playwright/test";
import { PASSWORD, signIn } from "./helpers";

async function auth(
  request: APIRequestContext,
): Promise<Record<string, string>> {
  const login = await request.post("/api/auth/login", {
    data: { email: "owner@demo.example", password: PASSWORD },
  });
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

/** A fresh New order, so the test reruns on the same database (tiny quantity: no stock pressure). */
async function newOrder(
  request: APIRequestContext,
): Promise<{ id: string; number: string }> {
  const headers = await auth(request);
  const customers = await (
    await request.get("/api/customers/options", { headers })
  ).json();
  const products = await (
    await request.get("/api/catalog/products", { headers })
  ).json();
  const nuts = products.find(
    (p: { name: string }) => p.name === "M16 hex nuts",
  );
  const ship = new Date(Date.now() + 25 * 86_400_000)
    .toISOString()
    .slice(0, 10);
  const r = await request.post("/api/orders", {
    headers,
    data: {
      customer_id: customers[0].id,
      product_id: nuts.id,
      quantity: "50",
      unit_price_paise: 1200,
      ship_date: ship,
      status: "new",
    },
  });
  expect(r.ok()).toBeTruthy();
  return r.json();
}

test("Selected orders: sent from Orders, on the timeline, synced back, options switch", async ({
  page,
  request,
}) => {
  const order = await newOrder(request);
  await signIn(page, "owner@demo.example");

  // Orders received → Send to Planning (a New order is accepted by sending it).
  await page.getByLabel("Search orders").fill(order.number);
  await page
    .getByRole("row", { name: new RegExp(order.number) })
    .getByRole("checkbox")
    .check();
  await page.getByRole("button", { name: "Send to Planning" }).click();
  await expect(page.getByText(/1 sent to Planning/).first()).toBeVisible();

  // Planning: ticked in the table, and on the timeline under "Your selection".
  await page.getByRole("link", { name: "Planning", exact: true }).click();
  await expect(page.getByLabel(`Include ${order.number}`)).toBeChecked();
  const yours = page.getByRole("button", { name: "Highlight Your selection" });
  await expect(yours).toContainText(order.number);
  await expect(page.getByText("21 days")).toBeVisible();

  // Untick here → no longer "In planning" in Orders received, and gone from the timeline.
  await page.getByLabel(`Include ${order.number}`).uncheck();
  await expect(yours).not.toContainText(order.number);
  const o = await (
    await request.get(`/api/orders/${order.id}`, {
      headers: await auth(request),
    })
  ).json();
  expect(o.marked_for_planning).toBe(false);

  // Tick again, then use an optimizer option: Current moves, then back to your selection.
  await page.getByLabel(`Include ${order.number}`).check();
  await expect(yours).toContainText(order.number);
  const use = page.getByRole("button", { name: "Use this selection" });
  if ((await use.count()) > 1) {
    await use.last().click(); // Fully optimized
    await expect(page.getByRole("columnheader", { name: /Fully optimized/ })).toContainText("Current");
    await expect(page.getByRole("button", { name: "✓ Using this" })).toHaveCount(1);
    await page.getByRole("columnheader", { name: /Your selection/ }).click();
    await page.getByRole("button", { name: "Use this selection" }).first().click(); // back to Your selection
    await expect(page.getByRole("columnheader", { name: /Your selection/ })).toContainText("Current");
  }

  // Steps 2–5 are locked for now.
  await expect(page.getByRole("tab", { name: /Production schedule/ })).toHaveAttribute("aria-disabled", "true");
  await page.goto("/planning?step=3");
  await expect(page.getByText(/coming soon/i).first()).toBeVisible();

  // Clean up: cancel the test order so reruns keep the planning pool small.
  await request.post(`/api/orders/${order.id}/cancel`, { headers: await auth(request), data: { reason: "e2e test order" } });
});
