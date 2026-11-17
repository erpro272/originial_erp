import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { expect, test } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { ActionsCard } from "./Actions";
import type { Action } from "./api";

const HASH = "a".repeat(64);
const base = {
  status: "pending",
  allowed: true,
  needs: "Planning edit access",
  payload_hash: HASH,
  editable: [],
  note: null,
  result: null,
  expires_at: "2026-11-18T10:00:00Z",
};
const ACTIONS: Action[] = [
  {
    id: "fix:p1:night",
    proposal_id: "p1",
    kind: "plan_fix",
    label: "Night shift on CNC 01",
    detail: "Cost ₹6,200",
    ...base,
  },
  {
    id: "fix:p1:express",
    proposal_id: "p2",
    kind: "plan_fix",
    label: "Express steel wire rod",
    detail: "Cost ₹4,000",
    ...base,
  },
  {
    id: "po:m1",
    proposal_id: "p3",
    kind: "raise_po",
    label: "Raise a PO for 2.4 t steel wire rod",
    ...base,
    allowed: false,
    needs: "Purchasing edit access",
  },
];

function Harness() {
  const [a, setA] = useState(ACTIONS);
  return <ActionsCard actions={a} onChange={setA} />;
}

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: ["ai.use"] })),
];
const proposal = (id: string, label: string, extra = {}) => ({
  id,
  kind: "plan_fix",
  label,
  detail: null,
  ...base,
  ...extra,
});

test("tick, review (re-checked live: now vs after), confirm: applied with a link; nothing without approval", async () => {
  let approved: unknown = null;
  mockApi(
    ...signedIn(),
    route("POST", "/api/ai/proposals/p1/preview", () =>
      json({
        proposal: proposal("p1", "Night shift on CNC 01"),
        ok: true,
        lines: ["Adds “Night shift on CNC 01” to PLAN-001."],
        rows: [
          { k: "Contribution", now: "₹9.88 L", then: "₹10.05 L" },
          { k: "Late orders", now: "1", then: "0" },
        ],
        warnings: [],
        error: null,
      }),
    ),
    route("POST", "/api/ai/proposals/approve", async (req) => {
      approved = await req.json();
      return json([
        proposal("p1", "Night shift on CNC 01", {
          status: "executed",
          result: {
            summary: "Night shift on CNC 01: applied to PLAN-001",
            href: "/planning/x?step=4",
          },
        }),
      ]);
    }),
    route("POST", "/api/ai/proposals/p2/reject", () =>
      json(proposal("p2", "Express steel wire rod", { status: "rejected" })),
    ),
  );
  renderApp(<Harness />);
  const card = screen.getByRole("region", { name: "Recommended actions" });
  const apply = within(card).getByRole("button", { name: "Apply to plan" });
  expect(apply).toBeDisabled(); // nothing ticked
  expect(within(card).getByText("Needs Purchasing edit access")).toBeInTheDocument();
  expect(within(card).getAllByRole("checkbox")[2]).toBeDisabled();

  fireEvent.click(within(card).getAllByRole("checkbox")[0]!);
  fireEvent.click(apply);
  const dlg = await screen.findByRole("dialog", { name: "Review before applying" });
  expect(await within(dlg).findByText("₹10.05 L")).toBeInTheDocument();
  expect(approved).toBeNull(); // reviewing changes nothing
  fireEvent.click(within(dlg).getByRole("button", { name: "Confirm and apply" }));
  await waitFor(() => expect(within(card).getByText("Applied")).toBeInTheDocument());
  expect(approved).toEqual({ items: [{ id: "p1", payload_hash: HASH }] });
  expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute(
    "href",
    "/planning/x?step=4",
  );

  fireEvent.click(within(card).getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(within(card).getByText("Dismissed")).toBeInTheDocument());
});

test("a suggestion that no longer applies can't be confirmed", async () => {
  mockApi(
    ...signedIn(),
    route("POST", "/api/ai/proposals/p2/preview", () =>
      json({
        proposal: proposal("p2", "Express steel wire rod"),
        ok: false,
        lines: [],
        rows: [],
        warnings: [],
        error: "This fix is no longer suggested for the plan (something changed).",
      }),
    ),
  );
  renderApp(<Harness />);
  const card = screen.getByRole("region", { name: "Recommended actions" });
  fireEvent.click(within(card).getAllByRole("checkbox")[1]!);
  fireEvent.click(within(card).getByRole("button", { name: "Apply to plan" }));
  const dlg = await screen.findByRole("dialog", { name: "Review before applying" });
  expect(await within(dlg).findByRole("alert")).toHaveTextContent("no longer suggested");
  expect(within(dlg).getByRole("button", { name: "Confirm and apply" })).toBeDisabled();
});
