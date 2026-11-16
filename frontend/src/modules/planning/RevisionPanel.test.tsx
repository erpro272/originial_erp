import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import type { Plan } from "./api";
import { RevisionPanel } from "./RevisionPanel";

test("shows what changed since approval, which changes need re-approval, and why", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", () => json({ ...ME, permissions: ["planning.read"] })),
  );
  const plan = {
    status: "approved",
    needs_reapproval: true,
    revision: {
      number: 2,
      against: 1,
      needed: true,
      causes: ["CNC 01 downtime added 20 Nov (8 h)", "WR8 stock 3 → 3.5 t"],
      changes: [
        {
          kind: "order_later",
          significant: true,
          title: "ORD-1041 now finishes 26 Nov (approved 22 Nov) · now 2 days late",
          why: ["CNC 01 downtime added 20 Nov (8 h)"],
        },
        {
          kind: "material_ok",
          significant: false,
          title: "Steel wire rod no longer short",
          why: [],
        },
      ],
    },
  } as unknown as Plan;
  renderApp(<RevisionPanel plan={plan} />);
  expect(await screen.findByText("What changed since approved version v1")).toBeInTheDocument();
  expect(screen.getByText("Rev 2 needs re-approval")).toBeInTheDocument();
  expect(screen.getByText(/ORD-1041 now finishes 26 Nov/)).toBeInTheDocument();
  expect(screen.getByText("Why: CNC 01 downtime added 20 Nov (8 h)")).toBeInTheDocument();
  expect(screen.getByText("For information")).toBeInTheDocument();
});
