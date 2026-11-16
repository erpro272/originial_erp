import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { KitIcon } from "@/components/kit/Kit";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import {
  fromMessage,
  streamChat,
  useConversation,
  useDeleteConversation,
  useStatus,
  type ChatEvent,
  type ContextCard,
  type Turn,
  type Widget,
} from "./api";
import { ContextPanel } from "./ContextPanel";
import { QUICK_PROMPTS } from "./prompts";
import { Sidebar, Sparkle } from "./Sidebar";
import { ActionsCard, RelatedChips, WidgetView } from "./Widgets";

/** Tiny, safe formatter for the model's text: paragraphs, "- " bullets and **bold** (no HTML). */
function Text({ text }: { text: string }) {
  const bold = (s: string): ReactNode[] =>
    s
      .split(/(\*\*[^*]+\*\*)/g)
      .map((p, i) => (p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p));
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length)
      blocks.push(
        <ul key={`u${blocks.length}`} className="m-0 flex list-disc flex-col gap-1 pl-5">
          {list.map((l, i) => (
            <li key={i}>{bold(l)}</li>
          ))}
        </ul>,
      );
    list = [];
  };
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (/^[-*•] /.test(t)) list.push(t.slice(2));
    else {
      flush();
      if (t)
        blocks.push(
          <p key={`p${blocks.length}`} className="m-0">
            {bold(t)}
          </p>,
        );
    }
  }
  flush();
  return <div className="flex flex-col gap-2 text-[14px] leading-relaxed text-ink">{blocks}</div>;
}

function StatusPills({ turn }: { turn: Turn }) {
  if (!turn.status.length) return null;
  return (
    <ul aria-label="Steps" className="m-0 flex list-none flex-wrap gap-2 p-0">
      {turn.status.map((s) => (
        <li
          key={s.id}
          className={cn(
            "flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px]",
            !s.done
              ? "border-bl-line bg-bl-bg text-bl"
              : s.ok
                ? "border-line bg-white text-ink-3"
                : "border-hi-line bg-hi-bg text-hi",
          )}
        >
          {!s.done ? (
            <span
              className="size-2.5 animate-spin rounded-full border-2 border-bl border-t-transparent"
              aria-hidden="true"
            />
          ) : (
            <span aria-hidden="true">{s.ok ? "✓" : "!"}</span>
          )}
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  if (turn.role === "user")
    return (
      <div className="flex justify-end">
        <p className="m-0 max-w-[80%] rounded-2xl rounded-tr-md bg-bl-bg px-4 py-2.5 text-[14px] text-ink">
          {turn.content}
        </p>
      </div>
    );
  const thinking = turn.pending && !turn.content && !turn.widgets.length;
  return (
    <article aria-label="Assistant answer" className="flex gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-ai-bg text-ai">
        <Sparkle className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <StatusPills turn={turn} />
        {thinking && !turn.status.length && (
          <span className="text-[13px] text-muted">Thinking…</span>
        )}
        {turn.content && <Text text={turn.content} />}
        {turn.widgets.map((w: Widget, i) => (
          <WidgetView key={i} w={w} />
        ))}
        {turn.actions.length > 0 && <ActionsCard actions={turn.actions} />}
        {turn.related.length > 0 && <RelatedChips items={turn.related} />}
        {turn.error && (
          <p
            role="alert"
            className="m-0 rounded-card border border-hi-line bg-hi-bg px-3 py-2 text-[13px] text-hi"
          >
            {turn.error}
          </p>
        )}
      </div>
    </article>
  );
}

const empty = (id: string, role: Turn["role"], content = ""): Turn => ({
  id,
  role,
  content,
  widgets: [],
  actions: [],
  related: [],
  context: [],
  status: [],
});

/** The AI Assistant workspace: full screen, three columns (history · chat · ERP context). */
export function AssistantPage() {
  const [params, setParams] = useSearchParams();
  const cid = params.get("c");
  const nav = useNavigate();
  const loc = useLocation();
  const back = (loc.state as { from?: string } | null)?.from;
  const qc = useQueryClient();
  const status = useStatus();
  const conv = useConversation(cid);
  const del = useDeleteConversation();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const seq = useRef(0);
  // load the opened conversation (state adjusted during render, not in an effect); a turn being streamed wins
  const source = cid ? (conv.data ? `${cid}:${conv.dataUpdatedAt}` : null) : "none";
  const [loaded, setLoaded] = useState<string | null>(null);
  if (!busy && source !== null && source !== loaded) {
    setLoaded(source);
    setTurns(cid && conv.data ? conv.data.messages.map(fromMessage) : []);
  }
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" }); // newer browsers return a Promise: never return it
  }, [turns]);

  const cards = useMemo(() => {
    const seen = new Set<string>();
    const out: ContextCard[] = [];
    for (const t of [...turns].reverse())
      for (const c of t.context) {
        const k = `${c.kind}:${c.key}`;
        if (!seen.has(k)) {
          seen.add(k);
          out.push(c);
        }
      }
    return out.slice(0, 3);
  }, [turns]);

  const send = async (text: string) => {
    const msg = text.trim();
    if (!msg || busy) return;
    setDraft("");
    setBusy(true);
    seq.current += 2;
    const aid = `a${seq.current}`;
    setTurns((t) => [
      ...t,
      empty(`u${seq.current}`, "user", msg),
      { ...empty(aid, "assistant"), pending: true },
    ]);
    const patch = (fn: (t: Turn) => Turn) =>
      setTurns((all) => all.map((t) => (t.id === aid ? fn(t) : t)));
    const on = ({ event, data }: ChatEvent) => {
      if (event === "start" && !cid)
        setParams({ c: String(data.conversation_id) }, { replace: true });
      else if (event === "tool_start")
        patch((t) => ({
          ...t,
          status: [
            ...t.status,
            {
              id: String(data.id),
              tool: String(data.tool),
              label: String(data.label),
              done: false,
              ok: true,
            },
          ],
        }));
      else if (event === "tool_result")
        patch((t) => ({
          ...t,
          status: t.status.map((s) =>
            s.id === data.id ? { ...s, done: true, ok: Boolean(data.ok) } : s,
          ),
        }));
      else if (event === "ui_widget")
        patch((t) => ({ ...t, widgets: [...t.widgets, data.widget as Widget] }));
      else if (event === "token") patch((t) => ({ ...t, content: t.content + String(data.text) }));
      else if (event === "approval_required")
        patch((t) => ({ ...t, actions: data.actions as Turn["actions"] }));
      else if (event === "related_records")
        patch((t) => ({ ...t, related: data.records as Turn["related"] }));
      else if (event === "context_update")
        patch((t) => ({ ...t, context: data.cards as ContextCard[] }));
      else if (event === "error") patch((t) => ({ ...t, error: String(data.message) }));
    };
    try {
      await streamChat(msg, cid, on);
    } catch {
      patch((t) => ({ ...t, error: "The connection was interrupted. Try again." }));
    } finally {
      patch((t) => ({ ...t, pending: false }));
      // reload the saved conversation before handing the screen back to it (never a copy older than this turn)
      await qc.refetchQueries({ queryKey: ["assistant", "conversation"] });
      setBusy(false);
      void qc.invalidateQueries({ queryKey: ["assistant", "list"] });
      inputRef.current?.focus();
    }
  };

  const newChat = () => {
    setParams({}, { replace: false });
    setTurns([]);
    inputRef.current?.focus();
  };

  return (
    <div className="grid h-[calc(100vh-65px)] grid-cols-1 bg-white lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_330px]">
      <div className="hidden min-h-0 lg:flex lg:flex-col">
        <Sidebar activeId={cid} onOpen={(id) => setParams({ c: id })} onNew={newChat} />
      </div>
      <section aria-label="Chat" className="flex min-h-0 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
          <div className="flex items-center gap-3">
            <Sparkle className="size-6 text-primary" />
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <h1 className="m-0 text-[20px] font-bold text-ink">AI Assistant</h1>
                <Tag tone="bl" size="sm">
                  Manufacturing ERP
                </Tag>
                {status.data?.mode === "mock" && (
                  <Tag tone="md" size="sm">
                    Demo mode · no AI key
                  </Tag>
                )}
              </div>
              <span className="text-[12px] text-muted">
                Ask about orders, planning, production, materials, costs and more.
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={newChat}
              className="cursor-pointer rounded-full border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:bg-surface lg:hidden"
            >
              + New
            </button>
            {cid && (
              <button
                type="button"
                onClick={() => del.mutate(cid, { onSuccess: newChat })}
                className="flex cursor-pointer items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:bg-surface"
              >
                <span aria-hidden="true">🗑</span> Clear conversation
              </button>
            )}
            <button
              type="button"
              aria-label="Close the assistant"
              onClick={() => nav(back ?? "/")}
              className="grid size-8 cursor-pointer place-items-center rounded-full border border-line text-ink-3 hover:bg-surface"
            >
              ×
            </button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-5">
          {turns.length === 0 ? (
            <div className="m-auto flex max-w-[560px] flex-col items-center gap-4 text-center">
              <span className="grid size-14 place-items-center rounded-2xl bg-ai-bg text-ai">
                <Sparkle className="size-7" />
              </span>
              <h2 className="m-0 text-[22px] font-bold text-ink">
                How can I help with your operations?
              </h2>
              <p className="m-0 text-[14px] text-muted">
                Answers come from your live ERP data: schedules, orders, plans, stock, purchases and
                money. I suggest changes; you decide.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {["Is CNC 01 busy tomorrow?", ...QUICK_PROMPTS.slice(0, 3)].map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => void send(q)}
                    className="cursor-pointer rounded-full border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:bg-surface"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto flex w-full max-w-[860px] flex-col gap-6">
              {turns.map((t) => (
                <Bubble key={t.id} turn={t} />
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(draft);
          }}
          className="border-t border-line px-6 py-4"
        >
          <div className="mx-auto flex max-w-[860px] items-end gap-2 rounded-card border border-line-input bg-white p-2 focus-within:border-primary">
            <button
              type="button"
              disabled
              aria-label="Attach a document"
              title="Uploading SOPs and documents comes in the next step"
              className="grid size-9 shrink-0 cursor-not-allowed place-items-center rounded-full text-ink-3 opacity-50"
            >
              📎
            </button>
            <label className="sr-only" htmlFor="ai-input">
              Message
            </label>
            <textarea
              id="ai-input"
              ref={inputRef}
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
              placeholder="Ask anything about your operations…"
              className="max-h-40 min-h-9 flex-1 resize-none border-0 bg-transparent px-1 py-2 text-[14px] outline-none"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              aria-label="Send"
              className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-lg bg-primary text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              <KitIcon kind="upload" className="size-4 rotate-45" />
            </button>
          </div>
          <p className="mx-auto mt-1.5 max-w-[860px] text-[11px] text-muted">
            Enter to send · Shift+Enter for a new line. The assistant reads your ERP data with your
            role&apos;s access and never changes anything by itself.
          </p>
        </form>
      </section>
      <div className="hidden min-h-0 xl:flex xl:flex-col">
        <ContextPanel
          cards={cards}
          busy={busy}
          onPrompt={(q) => void send(q)}
          onDraft={(q) => (setDraft(q), inputRef.current?.focus())}
        />
      </div>
    </div>
  );
}
