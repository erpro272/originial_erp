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
    await expect(
      page.getByRole("columnheader", { name: /Fully optimized/ }),
    ).toContainText("Current");
    await expect(
      page.getByRole("button", { name: "✓ Using this" }),
    ).toHaveCount(1);
    await page.getByRole("columnheader", { name: /Your selection/ }).click();
    await page
      .getByRole("button", { name: "Use this selection" })
      .first()
      .click(); // back to Your selection
    await expect(
      page.getByRole("columnheader", { name: /Your selection/ }),
    ).toContainText("Current");
  }

  // Steps 4–5 are locked for now.
  await expect(
    page.getByRole("tab", { name: /Financial analysis/ }),
  ).toHaveAttribute("aria-disabled", "true");
  await page.goto("/planning?step=4");
  await expect(
    page.getByText(/no plan generated yet|coming next/i).first(),
  ).toBeVisible();

  // Clean up: cancel the test order so reruns keep the planning pool small.
  await request.post(`/api/orders/${order.id}/cancel`, {
    headers: await auth(request),
    data: { reason: "e2e test order" },
  });
});

test("Proposed manufacturing sequence: generate, hint with undo, lock keeps its slot under a rule", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/planning");
  await page
    .getByRole("button", { name: /Generate plan →|Recalculate plan →/ })
    .click();
  await expect(page).toHaveURL(/step=2/);
  await expect(page.getByText("Plan overview")).toBeVisible();
  await expect(page.getByText(/^Generated today, \d\d:\d\d$/)).toBeVisible();
  const feas = page.getByLabel("Plan feasibility");
  await expect(feas.getByText(/Feasible|Needs adjustment/)).toBeVisible();
  const rows = page.locator('[data-testid^="seq-"]');
  const order = async () =>
    rows.evaluateAll((els) =>
      els.map((e) => (e as HTMLElement).dataset.testid),
    );
  await expect(rows.first()).toBeVisible();

  // Rules re-sort; Custom is kept as the owner left it.
  await page.getByRole("tab", { name: "Deadline", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "Deadline", exact: true }),
  ).toHaveAttribute("aria-selected", "true");

  // The suggestion, if there is one: apply it, see the effect, then undo.
  const apply = page.getByRole("button", { name: "Apply this order" });
  if (await apply.count()) {
    const was = await order();
    await apply.click();
    await expect(
      page.getByRole("status").filter({ hasText: "Undo" }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Custom", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.getByRole("button", { name: "Undo" }).click();
    await expect.poll(order).toEqual(was);
  }

  // Lock the last order, sort by value: it keeps its slot. Then unlock.
  const ids = await order();
  const last = ids[ids.length - 1]!.slice(4);
  await page.getByRole("button", { name: `Lock ${last}` }).click();
  await expect(
    page.getByRole("button", { name: `Unlock ${last}` }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Highest value" }).click();
  await expect(
    page.getByRole("tab", { name: "Highest value" }),
  ).toHaveAttribute("aria-selected", "true");
  await expect.poll(async () => (await order()).at(-1)).toBe(`seq-${last}`);
  await page.getByRole("button", { name: `Unlock ${last}` }).click();
  await expect(
    page.getByRole("button", { name: `Lock ${last}` }),
  ).toBeVisible();
});

test("Production schedule: chart, reorder warning (cancel / continue), undo, save", async ({
  page,
}) => {
  await signIn(page, "owner@demo.example");
  await page.goto("/planning");
  await page
    .getByRole("button", { name: /Generate plan →|Recalculate plan →/ })
    .click();
  await page
    .getByRole("button", { name: "Next: Production schedule →" })
    .click();
  await expect(page).toHaveURL(/step=3/);
  await expect(page.getByText("Machine load")).toBeVisible();
  await expect(page.getByText("In production · locked")).toBeVisible();
  const rows = page.locator('[data-testid^="gantt-"]');
  const order = async () =>
    rows.evaluateAll((els) =>
      els.map((e) => (e as HTMLElement).dataset.testid!.slice(6)),
    );
  await expect(rows.first()).toBeVisible();
  const was = await order();

  // move the first order to the bottom with the keyboard
  const handle = page.getByRole("button", {
    name: `Drag to reorder ${was[0]}`,
  });
  const move = async () => {
    await handle.focus();
    await page.keyboard.press("Space");
    await page.waitForTimeout(150); // let dnd-kit pick the row up
    for (let i = 1; i < was.length; i++) {
      await page.keyboard.press("ArrowDown");
      await page.waitForTimeout(120);
    }
    await page.keyboard.press("Space");
  };
  await move();
  const dialog = page.getByRole("dialog");
  const toast = page.getByText(/Reordered|Schedule updated/).first();
  await expect(dialog.or(toast)).toBeVisible();
  if (await dialog.isVisible()) {
    await expect(dialog).toContainText(`Moving ${was[0]}`);
    await page.getByRole("button", { name: "Cancel, keep old order" }).click();
    await expect.poll(order).toEqual(was);
    await move();
    await page.getByRole("button", { name: "Continue anyway" }).click();
  }
  await expect.poll(async () => (await order()).at(-1)).toBe(was[0]);

  // undo puts it back; save clears the undo list
  await page.getByRole("button", { name: "↶ Undo" }).click();
  await expect.poll(order).toEqual(was);
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("Schedule saved").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "↶ Undo" })).toBeDisabled();
});
