import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { groupOf } from "./api";
import { AssistantPage } from "./AssistantPage";

const sse = (events: [string, Record<string, unknown>][]) =>
  new Response(
    events
      .map(
        ([e, d], i) =>
          `event: ${e}\ndata: ${JSON.stringify({ schema_version: 1, sequence: i + 1, ...d })}\n\n`,
      )
      .join(""),
    { headers: { "content-type": "text/event-stream" } },
  );

const TURN: [string, Record<string, unknown>][] = [
  ["start", { conversation_id: "c9", title: "Is CNC 01 busy tomorrow?" }],
  ["tool_start", { id: "t1", tool: "machine_schedule", label: "Checking CNC 01 schedule…" }],
  ["tool_result", { id: "t1", tool: "machine_schedule", ok: true, ms: 12, label: "done" }],
  [
    "ui_widget",
    {
      widget: {
        type: "section",
        title: "CNC 01 – Tue 17 Nov",
        badge: { label: "Busy", tone: "md" },
        text: "CNC 01 has 16 h booked of 16 h.",
        children: [
          {
            type: "table",
            columns: [
              { key: "order", label: "Order" },
              { key: "status", label: "Status" },
            ],
            rows: [{ order: "ORD-1034", status: "In production", status_tone: "bl" }],
          },
        ],
      },
    },
  ],
  [
    "ui_widget",
    {
      widget: {
        type: "bar_chart",
        title: "CNC 01 load (next 3 days)",
        unit: "%",
        bars: [
          { label: "Tue", value: 100 },
          { label: "Wed", value: 78 },
        ],
      },
    },
  ],
  ["ui_widget", { widget: { type: "nope", title: "never mounted" } }],
  ["token", { text: "CNC 01 is **fully booked** tomorrow. " }],
  ["token", { text: "ORD-1034 runs on it." }],
  [
    "approval_required",
    {
      actions: [
        {
          id: "night:m1:for:o1",
          label: "Add a night shift on CNC 01",
          detail: "Cost ₹6,200",
          kind: "plan_fix",
        },
      ],
      enabled: false,
    },
  ],
  [
    "related_records",
    { records: [{ kind: "order", label: "ORD-1034", href: "/orders?q=ORD-1034" }] },
  ],
  [
    "context_update",
    {
      cards: [
        {
          kind: "machine",
          key: "CNC 01",
          title: "CNC 01",
          badge: { label: "Busy", tone: "md" },
          items: [{ label: "Daily capacity", value: "16 h (2 shifts)" }],
        },
      ],
    },
  ],
  ["done", { conversation_id: "c9", mode: "mock" }],
];

const data = (kind: string) => TURN.find(([k]) => k === kind)![1];
const SAVED = [
  {
    id: "m1",
    role: "user",
    content: "Is CNC 01 busy tomorrow?",
    widgets: [],
    citations: [],
    actions: [],
    related: [],
    context: [],
    tools: [],
    error: null,
    created_at: "2026-11-16T10:00:00Z",
  },
  {
    id: "m2",
    role: "assistant",
    content: "CNC 01 is **fully booked** tomorrow. ORD-1034 runs on it.",
    widgets: TURN.filter(([k]) => k === "ui_widget").map(([, d]) => d.widget),
    citations: [],
    actions: data("approval_required").actions,
    related: data("related_records").records,
    context: data("context_update").cards,
    tools: [{ tool: "machine_schedule", label: "Checking CNC 01 schedule…", ok: true, ms: 12 }],
    error: null,
    created_at: "2026-11-16T10:00:01Z",
  },
];

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: ["ai.use"] })),
  route("GET", "/api/ai/status", () =>
    json({ mode: "mock", model: "mock", tools: ["machine_schedule"] }),
  ),
];

test("asks a question: live steps, typed widgets, answer, recommended actions (approval comes next), related records, context", async () => {
  const today = new Date().toISOString();
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/ai/conversations", () =>
      json([{ id: "c1", title: "Why is ORD-1042 delayed?", last_message_at: today }]),
    ),
    route("POST", "/api/ai/chat", () => sse(TURN)),
    route("GET", "/api/ai/conversations/c9", () =>
      json({
        id: "c9",
        title: "Is CNC 01 busy tomorrow?",
        last_message_at: today,
        messages: SAVED,
      }),
    ),
  );
  renderApp(<AssistantPage />, { path: "/assistant" });
  expect(await screen.findByText("Demo mode · no AI key")).toBeInTheDocument();
  const history = screen.getByRole("navigation", { name: "Conversation history" });
  expect(await within(history).findByText("Today")).toBeInTheDocument();
  expect(within(history).getByText("Why is ORD-1042 delayed?")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Is CNC 01 busy tomorrow?" },
  });
  fireEvent.keyDown(screen.getByLabelText("Message"), { key: "Enter" });

  // streamed live, then replaced by the saved copy of the same turn
  await waitFor(() => expect(screen.getByText("fully booked")).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Clear conversation" })).toBeInTheDocument(),
  );
  const answer = screen.getByRole("article", { name: "Assistant answer" });
  expect(within(answer).getByText("Checking CNC 01 schedule…")).toBeInTheDocument();
  expect(within(answer).getByText("CNC 01 – Tue 17 Nov")).toBeInTheDocument();
  expect(within(answer).getByText("In production")).toBeInTheDocument();
  expect(within(answer).getByRole("figure")).toHaveTextContent("CNC 01 load (next 3 days)"); // + sr-only table
  expect(within(answer).queryByText("never mounted")).not.toBeInTheDocument();
  const actions = within(answer).getByRole("region", { name: "Recommended actions" });
  expect(within(actions).getByText("Add a night shift on CNC 01")).toBeInTheDocument();
  expect(within(actions).getByRole("button", { name: "Apply to plan" })).toBeDisabled();
  expect(within(answer).getByRole("link", { name: /ORD-1034/ })).toHaveAttribute(
    "href",
    "/orders?q=ORD-1034",
  );
  const ctx = screen.getByRole("region", { name: "CNC 01 context" });
  expect(within(ctx).getByText("16 h (2 shifts)")).toBeInTheDocument();

  const post = calls.find((c) => new URL(c.url).pathname === "/api/ai/chat")!;
  expect(await post.json()).toEqual({ message: "Is CNC 01 busy tomorrow?", conversation_id: null });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Clear conversation" })).toBeInTheDocument(),
  );
});

test("history groups", () => {
  const now = new Date(2026, 10, 16, 12);
  expect(groupOf(new Date(2026, 10, 16, 9).toISOString(), now)).toBe("Today");
  expect(groupOf(new Date(2026, 10, 15, 9).toISOString(), now)).toBe("Yesterday");
  expect(groupOf(new Date(2026, 10, 12, 9).toISOString(), now)).toBe("This week");
  expect(groupOf(new Date(2026, 9, 1).toISOString(), now)).toBe("Earlier");
});
