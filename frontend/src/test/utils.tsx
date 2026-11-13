import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { Providers } from "@/app/providers";

type Handler = (req: Request) => Response | Promise<Response> | undefined;

/** Stub global fetch with a list of handlers; unmatched requests return 404. */
export function mockApi(...handlers: Handler[]) {
  const calls: Request[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init);
    calls.push(req.clone());
    for (const h of handlers) {
      const res = await h(req);
      if (res) return res;
    }
    return json({ error: { code: "not_found", message: "no mock" } }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

export const route =
  (
    method: string,
    path: string,
    respond: (req: Request) => Response | Promise<Response>,
  ): Handler =>
  (req) => {
    const u = new URL(req.url);
    return req.method === method && u.pathname === path ? respond(req) : undefined;
  };

export const ME = {
  id: "u1",
  email: "owner@demo.example",
  full_name: "Asha Rao",
  role: "owner",
  company: { id: "t1", name: "Demo Manufacturing Co.", role: "owner" },
  companies: [{ id: "t1", name: "Demo Manufacturing Co.", role: "owner" }],
  permissions: ["audit.read", "settings.read", "settings.write"],
};

export const signedInHandlers = (): Handler[] => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json(ME)),
  route("GET", "/api/me/preferences/table.audit-log.columns", () => json({ key: "x", value: {} })),
];

export function renderApp(ui: ReactElement, { path = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Providers client={client}>{ui}</Providers>
    </MemoryRouter>,
  );
}
