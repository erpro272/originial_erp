import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { json, mockApi, route } from "@/test/utils";
import * as csv from "@/lib/csv";
import { DataTable } from "./DataTable";
import { resolvePrefs } from "./useColumnPrefs";

interface Row {
  id: string;
  customer: string;
  sales: number;
  phone: string;
}
const h = createColumnHelper<Row>();
const columns = [
  h.accessor("id", { id: "id", header: "Order", meta: { label: "Order", alwaysVisible: true } }),
  h.accessor("customer", { id: "customer", header: "Customer", meta: { label: "Customer" } }),
  h.accessor("sales", { id: "sales", header: "Sales", meta: { label: "Sales", align: "right" } }),
  h.accessor("phone", {
    id: "phone",
    header: "Phone",
    meta: { label: "Phone", defaultHidden: true },
  }),
];
const data: Row[] = [
  { id: "ORD-1", customer: "Tata Motors", sales: 200, phone: "1" },
  { id: "ORD-2", customer: "Bajaj Auto", sales: 900, phone: "2" },
  { id: "ORD-3", customer: "Mahindra", sales: 500, phone: "3" },
];

function setup(saved: unknown = {}) {
  const api = mockApi(
    route("GET", "/api/me/preferences/table.t.columns", () => json({ key: "k", value: saved })),
    route("PUT", "/api/me/preferences/table.t.columns", async (r) =>
      json({ key: "k", ...(await r.json()) }),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DataTable<Row>
        tableId="t"
        title="All orders received"
        columns={columns}
        data={data}
        getRowId={(r) => r.id}
        csv={{ filename: "orders.csv" }}
      />
    </QueryClientProvider>,
  );
  return api;
}

const headers = () =>
  screen.getAllByRole("columnheader").map((th) => th.textContent?.replace(/[▲▼]/g, "").trim());

test("resolvePrefs merges saved order with new columns and keeps always-visible", () => {
  const cols = [
    { id: "a", label: "A", alwaysVisible: true },
    { id: "b", label: "B" },
    { id: "c", label: "C", defaultHidden: true },
  ];
  expect(resolvePrefs(cols, undefined)).toEqual({ order: ["a", "b", "c"], hidden: ["c"] });
  expect(resolvePrefs(cols, { order: ["b", "gone", "a"], hidden: ["a", "b"] })).toEqual({
    order: ["b", "a", "c"],
    hidden: ["b"],
  });
});

test("default-hidden columns are hidden; saved prefs reorder columns", async () => {
  setup({ order: ["customer", "id", "sales", "phone"], hidden: [] });
  await waitFor(() => expect(headers()).toEqual(["Customer", "Order", "Sales", "Phone"]));
});

test("column picker hides a column and saves the choice", async () => {
  const api = setup();
  await waitFor(() => expect(headers()).toEqual(["Order", "Customer", "Sales"]));
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Columns \(3\)/ }));
  await user.click(screen.getByRole("checkbox", { name: "Customer" }));
  await waitFor(() => expect(headers()).toEqual(["Order", "Sales"]));
  expect(screen.getByRole("checkbox", { name: "Order" })).toBeDisabled();
  const put = api.calls.find((c) => c.method === "PUT");
  expect(await put!.json()).toEqual({
    value: { order: ["id", "customer", "sales", "phone"], hidden: ["phone", "customer"] },
  });
});

test("client-side sorting: numbers sort high→low first, then low→high", async () => {
  setup();
  const user = userEvent.setup();
  const salesBtn = await screen.findByRole("button", { name: /Sales/ });
  await user.click(salesBtn);
  expect(screen.getByRole("columnheader", { name: /Sales/ })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  const firstCells = () =>
    screen
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell")[0]!.textContent);
  expect(firstCells()).toEqual(["ORD-2", "ORD-3", "ORD-1"]);
  await user.click(salesBtn);
  expect(firstCells()).toEqual(["ORD-1", "ORD-3", "ORD-2"]);
});

test("CSV export uses visible columns in order", async () => {
  setup();
  const spy = vi.spyOn(csv, "downloadCsv").mockImplementation(() => {});
  const user = userEvent.setup();
  await waitFor(() => expect(headers()).toEqual(["Order", "Customer", "Sales"]));
  await user.click(screen.getByRole("button", { name: "Export CSV" }));
  expect(spy).toHaveBeenCalledWith(
    "orders.csv",
    "Order,Customer,Sales\r\nORD-1,Tata Motors,200\r\nORD-2,Bajaj Auto,900\r\nORD-3,Mahindra,500",
  );
});
