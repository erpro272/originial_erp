import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch, unwrap, type Schemas } from "@/api/client";

export type Conversation = Schemas["ConversationOut"];
export type Message = Schemas["MessageOut"];

// ---- the SSE event contract (backend: app/ai/assistant/service.py, schema_version 1). Widgets / cards / chips are
// typed payloads rendered by our own components; unknown widget types are ignored, never mounted.
export type Tone = "hi" | "md" | "lo" | "ok" | "bl";
export interface Badge {
  label: string;
  tone: Tone;
}
export interface Column {
  key: string;
  label: string;
  align?: "right";
}
export type Widget =
  | {
      type: "section";
      title: string;
      badge?: Badge;
      icon?: "check" | "alert";
      text?: string;
      children: Widget[];
    }
  | {
      type: "table";
      title?: string;
      badge?: Badge;
      columns: Column[];
      rows: Record<string, string | null | undefined>[];
      empty?: string;
    }
  | {
      type: "bar_chart";
      title: string;
      unit: string;
      bars: { label: string; value: number; tone?: Tone | null }[];
    }
  | {
      type: "key_values";
      title: string;
      badge?: Badge;
      items: { label: string; value: string; tone?: Tone | null; link?: string }[];
    };
export interface Action {
  id: string;
  label: string;
  detail?: string;
  kind: string;
}
export interface Related {
  kind: string;
  label: string;
  href: string;
}
export interface ContextCard {
  kind: "machine" | "order" | "plan" | string;
  key: string;
  title: string;
  subtitle?: string;
  badge?: Badge;
  items: { label: string; value: string; tone?: Tone | null }[];
  link?: { label: string; href: string };
}
export interface Citation {
  document_id: string;
  title: string;
  page: number | null;
  url: string;
  snippet: string;
}
export interface ToolStatus {
  id: string;
  tool: string;
  label: string;
  done: boolean;
  ok: boolean;
}

export interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  widgets: Widget[];
  actions: Action[];
  related: Related[];
  context: ContextCard[];
  citations: Citation[];
  status: ToolStatus[];
  error?: string | null;
  pending?: boolean;
}

export function fromMessage(m: Message): Turn {
  return {
    id: m.id,
    role: m.role as Turn["role"],
    content: m.content,
    widgets: m.widgets as unknown as Widget[],
    actions: m.actions as unknown as Action[],
    related: m.related as unknown as Related[],
    context: m.context as unknown as ContextCard[],
    citations: m.citations as unknown as Citation[],
    status: (m.tools as { tool: string; ok: boolean; label?: string }[]).map((t, i) => ({
      id: String(i),
      tool: t.tool,
      label: t.label ?? t.tool.replace(/_/g, " "),
      done: true,
      ok: t.ok,
    })),
    error: m.error,
  };
}

const KEY = ["assistant"] as const;

export function useStatus() {
  return useQuery({
    queryKey: [...KEY, "status"],
    queryFn: async () => unwrap(await api.GET("/api/ai/status")),
    staleTime: 60_000,
  });
}

export function useConversations(q: string) {
  return useQuery({
    queryKey: [...KEY, "list", q],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(await api.GET("/api/ai/conversations", { params: { query: { q: q || undefined } } })),
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: [...KEY, "conversation", id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(await api.GET("/api/ai/conversations/{cid}", { params: { path: { cid: id! } } })),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.DELETE("/api/ai/conversations/{cid}", { params: { path: { cid: id } } });
      if (!r.response.ok) unwrap(r); // 204: no body on success
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}

export type ChatEvent = { event: string; data: Record<string, unknown> };

/** POST /api/ai/chat and read the typed SSE stream. */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch("/api/ai/chat", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!res.ok || !res.body) {
    let msg = "The assistant couldn't answer. Try again.";
    try {
      const b = (await res.json()) as { error?: { message?: string } };
      msg = b.error?.message ?? msg;
    } catch {
      /* not JSON */
    }
    onEvent({ event: "error", data: { message: msg } });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (data.length) {
        try {
          onEvent({ event, data: JSON.parse(data.join("\n")) as Record<string, unknown> });
        } catch {
          /* ignore a malformed event */
        }
      }
    }
  }
}

/** History groups like the mockup: Today, Yesterday, This week, Earlier. */
export function groupOf(
  iso: string,
  now = new Date(),
): "Today" | "Yesterday" | "This week" | "Earlier" {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "This week";
  return "Earlier";
}

// ---- company documents (RAG) ----

export type Document = Schemas["AiDocumentOut"];
export const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  planner: "Planner",
  purchaser: "Purchaser",
  accountant: "Accountant",
};

export function useDocuments(enabled = true) {
  return useQuery({
    queryKey: [...KEY, "documents"],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/ai/documents")),
    // poll while something is being indexed
    refetchInterval: (q) =>
      (q.state.data ?? []).some((d) => d.status === "queued" || d.status === "processing")
        ? 2000
        : false,
  });
}

export function useDocumentActions() {
  const qc = useQueryClient();
  const done = () => void qc.invalidateQueries({ queryKey: [...KEY, "documents"] });
  const upload = useMutation({
    mutationFn: async ({ file, title, roles }: { file: File; title: string; roles: string[] }) => {
      const fd = new FormData();
      fd.append("file", file);
      if (title.trim()) fd.append("title", title.trim());
      roles.forEach((r) => fd.append("roles", r));
      const res = await apiFetch("/api/ai/documents", { method: "POST", body: fd });
      const body = (await res.json()) as Document & { error?: { message?: string } };
      if (!res.ok) throw new Error(body.error?.message ?? "Upload failed.");
      return body;
    },
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      const r = await api.DELETE("/api/ai/documents/{did}", { params: { path: { did: id } } });
      if (!r.response.ok) unwrap(r);
    },
    onSuccess: done,
  });
  const reindex = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/ai/documents/{did}/reindex", { params: { path: { did: id } } })),
    onSuccess: done,
  });
  return { upload, remove, reindex };
}

/** Opens a cited document at its page with a fresh short-lived link (links saved in old answers expire). */
export async function openCitation(c: Citation) {
  const win = window.open("", "_blank"); // opened now (inside the click) so it isn't blocked as a pop-up
  if (win) win.opener = null;
  try {
    const r = unwrap(
      await api.GET("/api/ai/documents/{did}/link", { params: { path: { did: c.document_id } } }),
    );
    const url = r.url + (c.page ? `#page=${c.page}` : "");
    if (win) win.location.href = url;
    else window.open(url, "_blank", "noopener");
  } catch {
    win?.close();
  }
}
