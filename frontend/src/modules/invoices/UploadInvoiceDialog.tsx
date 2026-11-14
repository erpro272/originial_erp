import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { rupees } from "@/lib/format";
import { ACCEPT, MAX_MB, STATUS, uploadFiles, useUploads, type Batch } from "./api";

const UploadIcon = () => (
  <svg
    aria-hidden
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M12 15V3M7 8l5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
  </svg>
);

export function UploadInvoiceButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="pill" size="sm" className="font-semibold" onClick={() => setOpen(true)}>
        <UploadIcon /> Upload invoice
      </Button>
      {open && <UploadInvoiceDialog onClose={() => setOpen(false)} />}
    </>
  );
}

const fmtSize = (b: number) =>
  b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(b / 1024)} KB`;

export function UploadInvoiceDialog({ onClose }: { onClose: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<Batch | null>(null);
  const pick = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const add = (list: FileList | null) => {
    if (!list) return;
    const next = [...files];
    const problems: string[] = [];
    for (const f of Array.from(list)) {
      if (f.size > MAX_MB * 1024 * 1024) problems.push(`${f.name} is larger than ${MAX_MB} MB`);
      else if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    setFiles(next.slice(0, 25));
    setError(
      problems.length
        ? problems.join(". ")
        : next.length > 25
          ? "Upload at most 25 files at a time."
          : null,
    );
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setBatch(await uploadFiles(files));
      await qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Upload failed. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      width={680}
      title="Upload invoices"
      description="Photos, scans or PDFs of past invoices. Each one is read, then you check it before anything is saved."
      footer={
        batch ? (
          <>
            <Link
              to="/orders/customers/imports"
              onClick={onClose}
              className={cn(buttonVariants({ variant: "pill" }), "no-underline")}
            >
              All imports
            </Link>
            <Button onClick={onClose}>Done</Button>
          </>
        ) : (
          <>
            <Button variant="pill" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={start} disabled={!files.length || busy}>
              {busy
                ? "Uploading…"
                : `Upload ${files.length || ""} file${files.length === 1 ? "" : "s"}`}
            </Button>
          </>
        )
      }
    >
      {batch ? (
        <BatchProgress batch={batch} onNavigate={onClose} />
      ) : (
        <>
          <div
            onDragOver={(e) => (e.preventDefault(), setDrag(true))}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              add(e.dataTransfer.files);
            }}
            className={cn(
              "flex flex-col items-center gap-3 rounded-card border border-dashed border-faint bg-surface px-6 py-10 text-center",
              drag && "border-primary bg-surface-blue",
            )}
          >
            <span className="grid size-11 place-items-center rounded-full bg-bl-bg text-primary">
              <UploadIcon />
            </span>
            <b className="text-[15px]">Drop invoice files here</b>
            <span className="text-[13px] text-muted">
              JPG, PNG, HEIC or PDF · up to {MAX_MB} MB each · 25 files at a time
            </span>
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="pill" onClick={() => pick.current?.click()}>
                Choose files
              </Button>
              <Button variant="pill" onClick={() => camera.current?.click()} className="md:hidden">
                Take a photo
              </Button>
            </div>
            <input
              ref={pick}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              aria-label="Choose invoice files"
              onChange={(e) => add(e.target.files)}
            />
            <input
              ref={camera}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              aria-label="Take a photo of an invoice"
              onChange={(e) => add(e.target.files)}
            />
          </div>
          {error && (
            <p role="alert" className="m-0 text-sm text-hi">
              {error}
            </p>
          )}
          {files.length > 0 && (
            <ul className="m-0 list-none rounded-xl border border-divider p-0">
              {files.map((f, i) => (
                <li
                  key={`${f.name}-${i}`}
                  className="flex items-center justify-between gap-3 border-t border-divider px-4 py-2.5 text-sm first:border-t-0"
                >
                  <span className="truncate">{f.name}</span>
                  <span className="flex items-center gap-3 text-muted">
                    {fmtSize(f.size)}
                    <button
                      type="button"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles(files.filter((_, j) => j !== i))}
                      className="cursor-pointer rounded-lg border-0 bg-transparent px-2 text-lg text-subtle hover:bg-hi-bg hover:text-hi"
                    >
                      ×
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Modal>
  );
}

function BatchProgress({ batch, onNavigate }: { batch: Batch; onNavigate: () => void }) {
  const q = useUploads({ batch_id: batch.batch_id });
  const items = q.data?.items ?? batch.uploads;
  const s = q.data?.summary;
  const mock = items.some((u) => u.ai_mode === "mock");
  return (
    <div className="flex flex-col gap-4">
      {s && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["Being read", s.processing ?? 0],
            ["Need review", s.need_review ?? 0],
            ["Saved", s.imported ?? 0],
            ["Failed", s.failed ?? 0],
          ].map(([k, v]) => (
            <div key={k} className="rounded-xl border border-divider bg-surface px-3 py-2">
              <b className="block text-lg">{v}</b>
              <span className="text-xs text-muted">{k}</span>
            </div>
          ))}
        </div>
      )}
      {mock && <MockNotice />}
      <ul className="m-0 list-none rounded-xl border border-divider p-0">
        {items.map((u) => (
          <li
            key={u.id}
            className="flex flex-wrap items-center justify-between gap-3 border-t border-divider px-4 py-3 text-sm first:border-t-0"
          >
            <span className="flex min-w-0 flex-col">
              <span className="truncate font-medium">{u.file_name}</span>
              <small className="text-xs text-muted">
                {u.status === "failed"
                  ? u.error
                  : u.buyer_name
                    ? `${u.buyer_name} · ${u.invoice_number ?? "no number"}${u.grand_total_paise != null ? ` · ₹${rupees(u.grand_total_paise)}` : ""}`
                    : "Reading the invoice…"}
              </small>
            </span>
            <span className="flex items-center gap-3">
              <Tag tone={STATUS[u.status].tone}>{STATUS[u.status].label}</Tag>
              {(u.status === "needs_review" || u.status === "verified") && (
                <Link
                  to={`/orders/customers/imports/${u.id}`}
                  onClick={onNavigate}
                  className="font-medium"
                >
                  Review →
                </Link>
              )}
            </span>
          </li>
        ))}
        {batch.rejected.map((r) => (
          <li
            key={r.file_name}
            className="flex items-center justify-between gap-3 border-t border-divider px-4 py-3 text-sm first:border-t-0"
          >
            <span className="flex flex-col">
              <span className="font-medium">{r.file_name}</span>
              <small className="text-xs text-hi">{r.error}</small>
            </span>
            <Tag tone="hi">Not uploaded</Tag>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MockNotice() {
  return (
    <div className="rounded-xl border border-ai-line bg-ai-wash px-4 py-3 text-[13px] text-ink-2">
      <b className="text-ai">✦ AI demo mode.</b> No Anthropic API key is set, so details come from
      built-in sample data, not from your file. Upload the sample files in{" "}
      <span className="font-mono">samples/invoices</span> to see matching results, or add a key to
      read real invoices.
    </div>
  );
}
