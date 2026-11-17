import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { DocumentsSheet, Sources } from "./Documents";

const DOC = {
  id: "d1",
  title: "Costing Policy",
  file_name: "Costing Policy.pdf",
  size_bytes: 2048,
  roles: ["owner", "accountant"],
  status: "ready",
  error: null,
  pages: 2,
  chunks: 2,
  embedder: "BAAI/bge-small-en-v1.5",
  created_at: "2026-11-16T10:00:00Z",
  indexed_at: "2026-11-16T10:00:05Z",
  can_edit: true,
  url: "/api/files/tok1",
};

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: ["ai.use"] })),
];

test("documents: list with who can see each one, upload with roles, delete", async () => {
  let uploaded: FormData | null = null;
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/ai/documents", () => json([DOC])),
    route("POST", "/api/ai/documents", async (req) => {
      uploaded = await req.formData();
      return json({ ...DOC, id: "d2", title: "SOP-07", status: "queued", roles: ["planner"] }, 201);
    }),
    route("DELETE", "/api/ai/documents/d1", () => new Response(null, { status: 204 })),
  );
  renderApp(<DocumentsSheet open onOpenChange={() => {}} />);
  const list = await screen.findByRole("region", { name: "Documents" });
  expect(await within(list).findByText("Costing Policy")).toBeInTheDocument();
  expect(within(list).getByText(/visible to Owner, Accountant/)).toBeInTheDocument();
  expect(within(list).getByText("Ready")).toBeInTheDocument();

  const form = screen.getByRole("region", { name: "Upload a document" });
  const file = new File(["%PDF-1.4"], "SOP-07.pdf", { type: "application/pdf" });
  fireEvent.change(within(form).getByLabelText(/File/), { target: { files: [file] } });
  fireEvent.click(within(form).getByRole("checkbox", { name: "Planner" }));
  fireEvent.click(within(form).getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(uploaded).not.toBeNull());
  expect(uploaded!.getAll("roles")).toEqual(["planner"]);
  expect(await (uploaded!.get("file") as Blob).text()).toBe("%PDF-1.4"); // the file itself is sent

  fireEvent.click(within(list).getByRole("button", { name: "Delete Costing Policy" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
});

test("sources open the cited page with a fresh link", async () => {
  mockApi(
    ...signedIn(),
    route("GET", "/api/ai/documents/d1/link", () => json({ url: "/api/files/fresh" })),
  );
  const win = { opener: {}, location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
  renderApp(
    <Sources
      items={[
        {
          document_id: "d1",
          title: "Costing Policy",
          page: 2,
          url: "/api/files/old",
          snippet: "A variance above 5%…",
        },
      ]}
    />,
  );
  expect(screen.getByText("“A variance above 5%…”")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Costing Policy · page 2/ }));
  await waitFor(() => expect(win.location.href).toBe("/api/files/fresh#page=2"));
  expect(win.opener).toBeNull();
});
