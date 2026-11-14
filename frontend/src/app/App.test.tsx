import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { json, ME, mockApi, renderApp, route, signedInHandlers } from "@/test/utils";

test("signed out: protected route redirects to login", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ error: { code: "unauthorized", message: "x" } }, 401),
    ),
  );
  renderApp(<App />, { path: "/planning" });
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
});

test.each(["Purchasing", "Production", "Billing", "Finance", "Dashboard"])(
  "%s shows the Coming soon page",
  async (name) => {
    mockApi(...signedInHandlers());
    renderApp(<App />, { path: `/${name.toLowerCase()}` });
    expect(await screen.findByRole("heading", { name: "Coming soon" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name })).toBeInTheDocument();
    expect(screen.getByRole("link", { name })).toHaveClass("border-primary");
  },
);

test("top nav lists the six modules and Dashboard last", async () => {
  mockApi(...signedInHandlers());
  renderApp(<App />, { path: "/orders" });
  const nav = await screen.findByRole("navigation", { name: "Main" });
  expect([...nav.querySelectorAll("a")].map((a) => a.textContent)).toEqual([
    "Orders",
    "Planning",
    "Purchasing",
    "Production",
    "Billing",
    "Finance",
    "Dashboard",
  ]);
});

test("login validates, then signs in", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ error: { code: "unauthorized", message: "x" } }, 401),
    ),
    route("POST", "/api/auth/login", () =>
      json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", () => json(ME)),
  );
  renderApp(<App />, { path: "/login" });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Email"), "owner@demo.example");
  await user.type(screen.getByLabelText("Password"), "Demo@12345");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1, name: "Orders" })).toBeInTheDocument(),
  );
  expect(screen.queryByText("Choose a company")).toBeNull();
});

test("wrong password shows the server message", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () => json({}, 401)),
    route("POST", "/api/auth/login", () =>
      json({ error: { code: "unauthorized", message: "Email or password is incorrect." } }, 401),
    ),
  );
  renderApp(<App />, { path: "/login" });
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "owner@demo.example");
  await user.type(screen.getByLabelText("Password"), "nope");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
});

test("audit log is blocked for roles without permission", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", () =>
      json({ ...ME, role: "planner", permissions: ["settings.read"] }),
    ),
  );
  renderApp(<App />, { path: "/settings/audit-log" });
  expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
});

test("expired access token is refreshed once and the request retried", async () => {
  let meCalls = 0;
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ access_token: "tok2", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", (r) => {
      meCalls++;
      return r.headers.get("authorization") === "Bearer tok2" && meCalls > 1
        ? json(ME)
        : json({ error: { code: "unauthorized", message: "expired" } }, 401);
    }),
  );
  renderApp(<App />, { path: "/orders" });
  expect(await screen.findByRole("heading", { level: 1, name: "Orders" })).toBeInTheDocument();
  expect(meCalls).toBe(2);
});
