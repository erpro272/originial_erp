import { useState } from "react";
import { useDebounced } from "@/lib/useDebounced";
import { cn } from "@/lib/cn";
import { groupOf, useConversations } from "./api";

const GROUPS = ["Today", "Yesterday", "This week", "Earlier"] as const;

export function Sparkle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M12 2.5c.4 3.9 2.6 6.1 6.5 6.5-3.9.4-6.1 2.6-6.5 6.5-.4-3.9-2.6-6.1-6.5-6.5 3.9-.4 6.1-2.6 6.5-6.5zM19 14c.2 1.9 1.1 2.8 3 3-1.9.2-2.8 1.1-3 3-.2-1.9-1.1-2.8-3-3 1.9-.2 2.8-1.1 3-3z" />
    </svg>
  );
}

/** Left column: title, + New conversation, search, history grouped by Today / Yesterday / This week / Earlier. */
export function Sidebar({
  activeId,
  onOpen,
  onNew,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const list = useConversations(q);
  const items = list.data ?? [];
  return (
    <aside
      aria-label="Conversations"
      className="flex min-h-0 flex-1 flex-col gap-4 border-r border-line bg-surface/60 p-5"
    >
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-ai-bg text-ai">
          <Sparkle className="size-5" />
        </span>
        <div className="flex flex-col">
          <h2 className="m-0 text-[17px] font-bold text-ink">AI Assistant</h2>
          <span className="text-[12px] text-muted">
            Ask about orders, planning, production, materials, costs and more.
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onNew}
        className="flex cursor-pointer items-center justify-center gap-2 rounded-card bg-primary px-4 py-2.5 text-[14px] font-semibold text-white hover:bg-primary-hover"
      >
        + New conversation
      </button>
      <label className="relative block">
        <span className="sr-only">Search conversations</span>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search conversations"
          className="w-full rounded-card border border-line-input bg-white px-3 py-2 text-[13px] outline-none focus:border-primary"
        />
      </label>
      <nav
        aria-label="Conversation history"
        className="-mx-2 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2"
      >
        {items.length === 0 && (
          <p className="m-0 text-[13px] text-muted">
            {q ? "No conversation matches." : "No conversations yet."}
          </p>
        )}
        {GROUPS.map((g) => {
          const rows = items.filter((c) => groupOf(c.last_message_at) === g);
          if (!rows.length) return null;
          return (
            <div key={g} className="flex flex-col gap-1">
              <h3 className="m-0 px-2 text-[12px] font-semibold text-muted">{g}</h3>
              {rows.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onOpen(c.id)}
                  aria-current={c.id === activeId ? "true" : undefined}
                  className={cn(
                    "flex cursor-pointer items-start gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-ink-2 hover:bg-white",
                    c.id === activeId && "bg-bl-bg font-medium text-primary hover:bg-bl-bg",
                  )}
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="mt-0.5 size-4 shrink-0 text-ink-3"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    aria-hidden="true"
                  >
                    <path d="M4 5h16v11H8l-4 4z" strokeLinejoin="round" />
                  </svg>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{c.title}</span>
                    <span className="text-[11px] text-muted">
                      {new Date(c.last_message_at)
                        .toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
                        .toUpperCase()}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
