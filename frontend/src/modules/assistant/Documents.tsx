import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { ROLE_LABEL, useDocumentActions, useDocuments, type Citation } from "./api";
import { openCitation } from "./api";

const STATUS: Record<string, { label: string; tone: TagTone }> = {
  queued: { label: "Waiting", tone: "lo" },
  processing: { label: "Reading…", tone: "bl" },
  ready: { label: "Ready", tone: "ok" },
  failed: { label: "Failed", tone: "hi" },
};

/** Company documents the assistant can quote: upload (PDF / Word / text), who may see each one, status, delete. */
export function DocumentsSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const docs = useDocuments(open);
  const { upload, remove, reindex } = useDocumentActions();
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!file) return;
    setError(null);
    upload.mutate(
      { file, title, roles },
      {
        onSuccess: (d) => {
          toast({
            title: `${d.title} uploaded`,
            description: "It's being read; answers can quote it in a moment.",
          });
          setFile(null);
          setTitle("");
          setRoles([]);
          if (fileRef.current) fileRef.current.value = "";
        },
        onError: (e) => setError(e instanceof Error ? e.message : "Upload failed."),
      },
    );
  };

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      eyebrow="AI Assistant"
      title="Company documents"
      description="SOPs, policies, manuals and specs the assistant can quote, with the document and page."
      width={620}
    >
      <div className="flex flex-col gap-5">
        <section
          aria-label="Upload a document"
          className="flex flex-col gap-3 rounded-card border border-line p-4"
        >
          <label className="flex flex-col gap-1 text-[13px] font-medium text-ink-2">
            File (PDF with text, Word .docx, .txt or .md · up to 20 MB)
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-[13px]"
            />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-medium text-ink-2">
            Title (optional)
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Costing Policy"
              className="rounded-md border border-line-input px-3 py-2 text-[14px] font-normal"
            />
          </label>
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium text-ink-2">
              Who can see it in answers
            </legend>
            <div className="flex flex-wrap gap-3 text-[13px]">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={roles.length === 0} onChange={() => setRoles([])} />
                Everyone
              </label>
              {Object.entries(ROLE_LABEL).map(([r, label]) => (
                <label key={r} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={roles.includes(r)}
                    onChange={(e) =>
                      setRoles((x) => (e.target.checked ? [...x, r] : x.filter((y) => y !== r)))
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          {error && (
            <p role="alert" className="m-0 text-[13px] text-hi">
              {error}
            </p>
          )}
          <div>
            <Button size="sm" onClick={submit} disabled={!file || upload.isPending}>
              {upload.isPending ? "Uploading…" : "Upload"}
            </Button>
          </div>
        </section>

        <section aria-label="Documents" className="flex flex-col gap-2">
          <h3 className="m-0 text-[14px] font-semibold text-ink">
            Documents ({docs.data?.length ?? 0})
          </h3>
          {docs.data?.length === 0 && (
            <p className="m-0 text-[13px] text-muted">
              No documents yet. Upload an SOP or a policy to ask about it.
            </p>
          )}
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {docs.data?.map((d) => {
              const st = STATUS[d.status] ?? { label: d.status, tone: "lo" as const };
              return (
                <li
                  key={d.id}
                  className="flex flex-col gap-1.5 rounded-card border border-line px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-[14px] font-semibold text-ink">{d.title}</span>
                      <Tag tone={st.tone} size="sm">
                        {st.label}
                      </Tag>
                    </span>
                    <span className="flex shrink-0 gap-2 text-[13px]">
                      <a href={d.url} target="_blank" rel="noreferrer" className="text-link">
                        Open
                      </a>
                      {d.can_edit && d.status === "failed" && (
                        <button
                          type="button"
                          className="cursor-pointer text-link"
                          onClick={() => reindex.mutate(d.id)}
                        >
                          Retry
                        </button>
                      )}
                      {d.can_edit && (
                        <button
                          type="button"
                          aria-label={`Delete ${d.title}`}
                          className="cursor-pointer text-hi"
                          onClick={() => remove.mutate(d.id)}
                        >
                          Delete
                        </button>
                      )}
                    </span>
                  </div>
                  <span className="text-[12px] text-muted">
                    {d.file_name} · {d.pages ? `${d.pages} page${d.pages === 1 ? "" : "s"} · ` : ""}
                    {d.chunks} passage{d.chunks === 1 ? "" : "s"} · visible to{" "}
                    {d.roles.length
                      ? d.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")
                      : "everyone"}
                  </span>
                  {d.error && <span className="text-[12px] text-hi">{d.error}</span>}
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </Sheet>
  );
}

/** Sources under an answer: document · page, with the quoted passage; opens the original at that page. */
export function Sources({ items }: { items: Citation[] }) {
  return (
    <div className="flex flex-col gap-2">
      <h4 className="m-0 text-[13px] font-semibold text-ink-2">Sources</h4>
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((c, i) => (
          <li
            key={`${c.document_id}:${c.page}`}
            className="rounded-card border border-line bg-surface/60 px-3 py-2"
          >
            <button
              type="button"
              onClick={() => void openCitation(c)}
              className="flex cursor-pointer items-center gap-2 text-left text-[13px] font-semibold text-link hover:underline"
            >
              <span className="grid size-5 place-items-center rounded-full bg-bl-bg text-[11px] text-bl">
                {i + 1}
              </span>
              {c.title}
              {c.page ? ` · page ${c.page}` : ""} ↗
            </button>
            <p className="m-0 mt-1 text-[12px] leading-relaxed text-ink-3">“{c.snippet}”</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
