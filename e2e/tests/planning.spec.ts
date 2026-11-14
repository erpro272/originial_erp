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

/** Creates a fresh accepted order sent to Planning, so the test can rerun on the same database. */
async function newPlanningOrder(
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
      quantity: "5000",
      unit_price_paise: 1200,
      ship_date: ship,
      status: "accepted",
    },
  });
  expect(r.ok()).toBeTruthy();
  const order = await r.json();
  await request.post("/api/orders/planning-selection", {
    headers,
    data: { order_ids: [order.id], marked: true },
  });
  return order;
}

test("plan: an order sent to Planning is planned, checked and approved", async ({
  page,
  request,
}) => {
  const order = await newPlanningOrder(request);
  await signIn(page, "owner@demo.example");
  await page.goto("/planning");

  // One working plan at a time: continue it, or start a new one.
  const start = page.getByRole("button", { name: "Start a plan" });
  const newPlan = page.getByRole("button", { name: "+ New plan" });
  await expect(
    start.or(page.getByRole("tab", { name: /Selected orders/ })),
  ).toBeVisible();
  if (await start.isVisible()) await start.click();
  else if (await newPlan.isEnabled()) await newPlan.click();

  // The order sent from Orders received is ticked automatically.
  await expect(page.getByLabel(`Include ${order.number}`)).toBeChecked();
  await expect(
    page.getByRole("heading", { name: /Order selection options/ }),
  ).toBeVisible();

  const generate = page.getByRole("button", { name: "Generate plan →" });
  if (await generate.isVisible()) await generate.click();
  else
    await page.getByRole("button", { name: /Next: Proposed sequence/ }).click();
  await expect(
    page.getByRole("heading", { name: "Proposed manufacturing sequence" }),
  ).toBeVisible();
  await expect(page.getByText("Plan overview")).toBeVisible();

  // Schedule: our order has a row; machine load is shown.
  await page.getByRole("tab", { name: /Production schedule/ }).click();
  await expect(
    page.getByRole("heading", { name: "Production schedule", level: 2 }),
  ).toBeVisible();
  await expect(page.getByText("Machine load")).toBeVisible();

  // Financials react to the late-penalty rule (company's choice, set via the small icon).
  await page.getByRole("tab", { name: /Financial analysis/ }).click();
  await page
    .getByRole("button", { name: /Late-delivery penalty: set your rule/ })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Late-delivery penalty" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  // Approve (raising any open material PO), then the order is planned with a promised date.
  await page.getByRole("tab", { name: /Final plan approval/ }).click();
  await page.getByRole("button", { name: /Approve (plan|again)/ }).click();
  const withPo = page.getByRole("button", { name: "Approve and raise PO" });
  if (await withPo.isVisible().catch(() => false)) await withPo.click();
  await expect(page.getByText("Plan approved").first()).toBeVisible();

  const o = await (
    await request.get(`/api/orders/${order.id}`, {
      headers: await auth(request),
    })
  ).json();
  expect(o.status).toBe("planned");
  expect(o.promised_date).toBeTruthy();
});
