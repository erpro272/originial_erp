import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { TextAreaField } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { longDate, rupees } from "@/lib/format";
import { STATES } from "@/lib/gst";
import { CustomerFormModal } from "../customers/CustomerFormModal";
import type { CustomerIn } from "../customers/api";
import {
  pct,
  STATUS,
  useFieldSpec,
  type Cell,
  type Check,
  type Doc,
  type FieldSpec,
  type Match,
  type UploadDetail,
} from "./api";
import { MockNotice } from "./UploadInvoiceDialog";

type Raw = string | null;
type Choice = { mode: "existing"; id: string } | { mode: "new"; body: CustomerIn } | null;
interface Focus {
  path: string;
  page: number | null;
  bbox: Cell["bbox"];
}

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function shown(type: string, value: unknown): string | null {
  if (value == null) return null;
  if (type === "money" && typeof value === "number")
    return `₹${rupees(value)}${value % 100 ? `.${String(Math.abs(value) % 100).padStart(2, "0")}` : ""}`;
  if (type === "date" && typeof value === "string") return longDate(value);
  if ((type === "state" || type === "state_code") && typeof value === "string")
    return `${value} · ${STATES[value] ?? ""}`;
  if (type === "bool") return value ? "Yes" : "No";
  return String(value);
}

export function ReviewPage() {
  const { uploadId = "" } = useParams();
  const spec = useFieldSpec();
  const detail = useQuery({
    queryKey: ["invoices", "upload", uploadId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/invoices/uploads/{upload_id}", {
          params: { path: { upload_id: uploadId } },
        }),
      ),
    refetchInterval: (q) =>
      ["uploaded", "extracting"].includes(q.state.data?.upload.status ?? "") ? 1500 : false,
  });
  if (detail.isPending || spec.isPending) return <LoadingState label="Opening the invoice…" />;
  if (detail.isError || !spec.data)
    return (
      <EmptyState
        title="Upload not found"
        description={(detail.error as Error | null)?.message}
        actions={<Link to="/orders/customers/imports">Back to imports</Link>}
      />
    );
  const d = detail.data;
  if (d.upload.status === "uploaded" || d.upload.status === "extracting")
    return <LoadingState label={`Reading ${d.upload.file_name}…`} />;
  return <Review key={`${d.upload.id}-${d.versions}`} detail={d} spec={spec.data} />;
}

function Review({ detail, spec }: { detail: UploadDetail; spec: FieldSpec }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();
  const u = detail.upload;
  const base = detail.document as unknown as Doc;
  const editable = u.status === "needs_review" || u.status === "verified";

  const [edits, setEdits] = useState<Record<string, Raw>>({});
  const [lines, setLines] = useState<Record<string, Raw>[] | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [acked, setAcked] = useState<Set<string>>(new Set());
  const [confirmDup, setConfirmDup] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [customerForm, setCustomerForm] = useState(false);
  const initialMatch = detail.match as unknown as Match;
  const [choice, setChoice] = useState<Choice>(
    initialMatch.kind === "existing" && initialMatch.customer_id
      ? { mode: "existing", id: initialMatch.customer_id }
      : null,
  );

  const draft = useMemo(() => ({ fields: edits, lines: lines ?? undefined }), [edits, lines]);
  const debounced = useDebounced(draft);
  const dirty = Object.keys(edits).length > 0 || lines !== null;
  const check = useQuery({
    queryKey: [
      "invoices",
      "check",
      u.id,
      debounced,
      choice?.mode === "existing" ? choice.id : null,
    ],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/invoices/uploads/{upload_id}/check", {
          params: {
            path: { upload_id: u.id },
            query: { customer_id: choice?.mode === "existing" ? choice.id : undefined },
          },
          body: debounced,
        }),
      ),
    enabled: editable,
    placeholderData: (prev) => prev,
  });
  const doc = (check.data?.document ?? base) as unknown as Doc;
  const checks = (check.data?.checks ?? detail.checks) as unknown as Check[];
  const match = (check.data?.match ?? detail.match) as unknown as Match;
  const dup = (check.data?.duplicate ?? detail.duplicate) as {
    flag: string;
    message: string | null;
  };
  const errors = checks.filter((c) => c.severity === "error");
  const warnings = checks.filter(
    (c) => c.severity === "warning" && c.code !== "possible_duplicate",
  );
  const unacked = warnings.filter((w) => !acked.has(w.id));
  const byPath = useMemo(() => {
    const m = new Map<string, Check[]>();
    checks.forEach((c) => m.set(c.path, [...(m.get(c.path) ?? []), c]));
    return m;
  }, [checks]);

  const lineRaw = (i: number, k: string): Raw =>
    lines ? (lines[i]?.[k] ?? null) : (base.lines[i]?.[k]?.raw ?? null);
  const lineCount = lines ? lines.length : base.lines.length;
  const editLine = (i: number, k: string, v: string) => {
    const cur =
      lines ??
      base.lines.map((ln) =>
        Object.fromEntries(spec.line_fields.map((f) => [f.key, ln[f.key]?.raw ?? null])),
      );
    setLines(cur.map((ln, j) => (j === i ? { ...ln, [k]: v === "" ? null : v } : ln)));
  };
  const goTo = (path: string) => {
    const [kind, a, b] = path.split(".");
    const cell = kind === "fields" ? doc.fields[a!] : doc.lines[Number(a)]?.[b!];
    if (cell?.page) setPage(cell.page);
    setFocus({ path, page: cell?.page ?? null, bbox: cell?.bbox ?? null });
    document.getElementById(`f-${path}`)?.focus();
  };

  const saveDraft = useMutation({
    mutationFn: async (verified: boolean) =>
      unwrap(
        await api.PUT("/api/invoices/uploads/{upload_id}/draft", {
          params: { path: { upload_id: u.id } },
          body: { ...draft, verified },
        }),
      ),
    onSuccess: async (_, verified) => {
      toast({
        title: verified ? "Marked as verified" : "Draft saved",
        description: "Your corrections are kept as a new version.",
        tone: "success",
      });
      await qc.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (e) =>
      toast({
        title: "Couldn't save",
        description: e instanceof ApiError ? e.message : undefined,
        tone: "error",
      }),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!choice) throw new ApiError(400, "customer", "Choose the customer first.");
      return unwrap(
        await api.POST("/api/invoices/uploads/{upload_id}/save", {
          params: { path: { upload_id: u.id } },
          body: {
            ...draft,
            customer:
              choice.mode === "existing"
                ? { mode: "existing", customer_id: choice.id }
                : { mode: "new", customer: choice.body },
            acknowledged: [...acked],
            confirm_possible_duplicate: confirmDup,
          },
        }),
      );
    },
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["invoices"] });
      await qc.invalidateQueries({ queryKey: ["customers"] });
      toast({
        title: "Invoice saved",
        description: `${r.customer_action === "new" ? "New customer created. " : ""}${r.order_number ? `Linked to ${r.order_number}.` : ""}`,
        tone: "success",
      });
      navigate(`/orders/customers/${r.customer_id}`);
    },
    onError: (e) =>
      toast({
        title: "Not saved",
        description: e instanceof ApiError ? e.message : "Check your connection.",
        tone: "error",
      }),
  });

  const blockers = [
    errors.length ? `${errors.length} error${errors.length > 1 ? "s" : ""} to fix` : null,
    unacked.length ? `${unacked.length} warning${unacked.length > 1 ? "s" : ""} to accept` : null,
    !choice ? "choose the customer" : null,
    dup.flag === "possible" && !confirmDup ? "confirm it isn't a duplicate" : null,
  ].filter(Boolean);

  const pages = detail.pages;
  const current = pages.find((p) => p.number === page) ?? pages[0];
  const highlight = focus && focus.bbox && focus.page === page ? focus.bbox : null;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Link to="/orders/customers/imports" className="text-sm font-medium no-underline">
            ← Invoice imports
          </Link>
          <h2 className="m-0 flex flex-wrap items-center gap-3 text-[22px] font-semibold tracking-[-0.01em]">
            Check the invoice <Tag tone={STATUS[u.status].tone}>{STATUS[u.status].label}</Tag>
          </h2>
          <p className="m-0 text-sm text-muted">
            {u.file_name} · read confidence {pct(u.overall_confidence)} · nothing is saved until you
            press Save
          </p>
        </div>
        {editable && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="ghost"
              className="text-hi hover:bg-hi-bg hover:text-hi"
              onClick={() => setRejectOpen(true)}
            >
              Reject
            </Button>
            <Button
              variant="pill"
              disabled={!dirty || saveDraft.isPending}
              onClick={() => saveDraft.mutate(false)}
            >
              Save draft
            </Button>
          </div>
        )}
      </div>
      {u.ai_mode === "mock" && <MockNotice />}
      {u.status === "failed" && <p className="m-0 text-sm text-hi">{u.error}</p>}

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        {/* LEFT: the original */}
        <section className="flex flex-col gap-2 lg:sticky lg:top-4" aria-label="Original invoice">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-1">
              {pages.map((p) => (
                <button
                  key={p.number}
                  type="button"
                  onClick={() => setPage(p.number)}
                  aria-current={p.number === page ? "page" : undefined}
                  className={cn(
                    "h-8 min-w-8 cursor-pointer rounded-full border-0 bg-transparent px-2.5 text-[13px] font-medium text-ink-2 hover:bg-surface-2",
                    p.number === page && "bg-bl-bg text-bl",
                  )}
                >
                  Page {p.number}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="pill"
                aria-label="Zoom out"
                onClick={() => setZoom((z) => Math.max(1, z - 0.5))}
                disabled={zoom <= 1}
              >
                −
              </Button>
              <span className="w-12 text-center text-[13px] text-muted tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <Button
                variant="pill"
                aria-label="Zoom in"
                onClick={() => setZoom((z) => Math.min(3, z + 0.5))}
                disabled={zoom >= 3}
              >
                +
              </Button>
              <a
                href={detail.original_url}
                target="_blank"
                rel="noreferrer"
                className="ml-2 text-[13px] font-medium"
              >
                Original ↗
              </a>
            </div>
          </div>
          <div className="h-[calc(100vh-160px)] min-h-[420px] overflow-auto rounded-card border border-line bg-surface">
            {current ? (
              <div className="relative" style={{ width: `${zoom * 100}%` }}>
                <img
                  src={current.url}
                  alt={`Page ${current.number} of ${u.file_name}`}
                  className="block w-full"
                />
                {highlight && (
                  <span
                    data-testid="highlight"
                    className="pointer-events-none absolute rounded-[3px] border-2 border-primary bg-primary/15"
                    style={{
                      left: `${highlight[0] * 100}%`,
                      top: `${highlight[1] * 100}%`,
                      width: `${(highlight[2] - highlight[0]) * 100}%`,
                      height: `${(highlight[3] - highlight[1]) * 100}%`,
                      margin: "-3px",
                      padding: "3px",
                      boxSizing: "content-box",
                    }}
                  />
                )}
              </div>
            ) : (
              <p className="p-6 text-sm text-muted">No preview available.</p>
            )}
          </div>
        </section>

        {/* RIGHT: extracted data */}
        <div className="flex min-w-0 flex-col gap-4">
          <ChecksCard
            errors={errors}
            warnings={warnings}
            acked={acked}
            setAcked={setAcked}
            onGo={goTo}
            editable={editable}
          />
          {doc.qr && <QrCard qr={doc.qr} checks={checks} />}
          {spec.sections
            .filter((s) => s.key !== "lines")
            .map((s) => {
              const fields = spec.fields.filter((f) => f.section === s.key);
              const found = fields.filter((f) => doc.fields[f.key]?.raw != null).length;
              const hasIssue = fields.some((f) => byPath.has(`fields.${f.key}`));
              return (
                <details
                  key={s.key}
                  open={found > 0 || hasIssue}
                  className="group rounded-card border border-line bg-white"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
                    <b className="text-[15px] font-semibold">{s.label}</b>
                    <span className="flex items-center gap-2 text-[13px] text-muted">
                      {hasIssue && (
                        <span
                          className="size-2 rounded-full bg-md-accent"
                          aria-label="has checks"
                        />
                      )}
                      {found} of {fields.length} found
                      <span aria-hidden className="transition-transform group-open:rotate-180">
                        ▾
                      </span>
                    </span>
                  </summary>
                  <div className="grid gap-x-4 gap-y-3 border-t border-divider px-5 py-4 sm:grid-cols-2">
                    {fields.map((f) => {
                      const cell = doc.fields[f.key] ?? ({ raw: null } as Cell);
                      const raw =
                        f.key in edits ? edits[f.key]! : (base.fields[f.key]?.raw ?? null);
                      return (
                        <FieldInput
                          key={f.key}
                          id={`f-fields.${f.key}`}
                          label={f.label}
                          type={f.type}
                          raw={raw}
                          cell={cell}
                          issues={byPath.get(`fields.${f.key}`) ?? []}
                          wide={
                            f.key.includes("address") ||
                            f.key === "amount_in_words" ||
                            f.key === "declaration" ||
                            f.key === "irn"
                          }
                          disabled={!editable || cell.masked}
                          active={focus?.path === `fields.${f.key}`}
                          onFocus={() => {
                            if (cell.page) setPage(cell.page);
                            setFocus({ path: `fields.${f.key}`, page: cell.page, bbox: cell.bbox });
                          }}
                          onChange={(v) =>
                            setEdits((e) => ({ ...e, [f.key]: v === "" ? null : v }))
                          }
                        />
                      );
                    })}
                  </div>
                </details>
              );
            })}
          <Card>
            <CardHeader
              title="4. Product / item details"
              suffix={`${lineCount} line${lineCount === 1 ? "" : "s"}`}
              actions={
                editable && (
                  <Button
                    variant="pill"
                    onClick={() =>
                      setLines([
                        ...(lines ??
                          base.lines.map((ln) =>
                            Object.fromEntries(
                              spec.line_fields.map((f) => [f.key, ln[f.key]?.raw ?? null]),
                            ),
                          )),
                        {},
                      ])
                    }
                  >
                    + Add line
                  </Button>
                )
              }
            />
            <div className="overflow-x-auto border-t border-divider">
              <table className="w-max min-w-full border-collapse text-[13px]">
                <thead className="bg-surface">
                  <tr>
                    <th className="px-2 py-2 text-left text-xs font-semibold text-muted">#</th>
                    {spec.line_fields.map((f) => (
                      <th
                        key={f.key}
                        className="px-2 py-2 text-left text-xs font-semibold whitespace-nowrap text-muted"
                      >
                        {f.label}
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: lineCount }, (_, i) => (
                    <tr key={i}>
                      <td className="border-t border-divider px-2 py-1.5 text-muted">{i + 1}</td>
                      {spec.line_fields.map((f) => {
                        const cell = doc.lines[i]?.[f.key];
                        const issues = byPath.get(`lines.${i}.${f.key}`) ?? [];
                        const path = `lines.${i}.${f.key}`;
                        return (
                          <td key={f.key} className="border-t border-divider px-1 py-1">
                            <input
                              id={`f-${path}`}
                              aria-label={`Line ${i + 1} ${f.label}`}
                              value={lineRaw(i, f.key) ?? ""}
                              placeholder="—"
                              disabled={!editable}
                              onFocus={() => {
                                if (cell?.page) setPage(cell.page);
                                setFocus({
                                  path,
                                  page: cell?.page ?? null,
                                  bbox: cell?.bbox ?? null,
                                });
                              }}
                              onChange={(e) => editLine(i, f.key, e.target.value)}
                              title={
                                issues.map((c) => c.message).join("\n") ||
                                (cell?.confidence != null
                                  ? `Read confidence ${pct(cell.confidence)}`
                                  : undefined)
                              }
                              className={cn(
                                "h-8 rounded-md border border-transparent bg-transparent px-1.5 outline-none hover:border-line-input focus:border-primary",
                                f.key === "product_name" || f.key === "description"
                                  ? "w-48"
                                  : "w-24",
                                cell?.confidence != null && cell.confidence < 0.75 && "bg-md-bg",
                                issues.some((c) => c.severity === "error")
                                  ? "border-hi-line bg-hi-wash"
                                  : issues.length
                                    ? "border-md-line bg-md-bg"
                                    : "",
                              )}
                            />
                          </td>
                        );
                      })}
                      <td className="border-t border-divider px-1">
                        {editable && (
                          <button
                            type="button"
                            aria-label={`Remove line ${i + 1}`}
                            onClick={() =>
                              setLines(
                                (
                                  lines ??
                                  base.lines.map((ln) =>
                                    Object.fromEntries(
                                      spec.line_fields.map((f) => [f.key, ln[f.key]?.raw ?? null]),
                                    ),
                                  )
                                ).filter((_, j) => j !== i),
                              )
                            }
                            className="cursor-pointer rounded-lg border-0 bg-transparent px-2 text-lg text-subtle hover:bg-hi-bg hover:text-hi"
                          >
                            ×
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {checks.some((c) => c.path.startsWith("lines.")) && (
              <ul className="m-0 list-none border-t border-divider px-5 py-3 text-[13px]">
                {checks
                  .filter((c) => c.path.startsWith("lines."))
                  .map((c) => (
                    <li key={c.id} className={c.severity === "error" ? "text-hi" : "text-md"}>
                      {c.message}
                    </li>
                  ))}
              </ul>
            )}
          </Card>

          {editable && (
            <CustomerCard
              match={match}
              choice={choice}
              setChoice={setChoice}
              onCreate={() => setCustomerForm(true)}
            />
          )}

          {editable && (
            <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-white px-5 py-4 shadow-tip">
              <div className="flex flex-col gap-1 text-sm">
                {dup.flag === "possible" && (
                  <label className="flex items-center gap-2 text-md">
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={confirmDup}
                      onChange={(e) => setConfirmDup(e.target.checked)}
                    />
                    {dup.message} Save anyway.
                  </label>
                )}
                <span className={blockers.length ? "text-muted" : "text-ok"}>
                  {blockers.length ? `Before saving: ${blockers.join(", ")}.` : "Ready to save."}
                </span>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="pill"
                  disabled={errors.length > 0 || saveDraft.isPending || u.status === "verified"}
                  onClick={() => saveDraft.mutate(true)}
                >
                  Mark verified
                </Button>
                <Button
                  disabled={blockers.length > 0 || save.isPending}
                  onClick={() => save.mutate()}
                >
                  {save.isPending ? "Saving…" : "Save invoice"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {rejectOpen && <RejectModal uploadId={u.id} onClose={() => setRejectOpen(false)} />}
      {customerForm && (
        <CustomerFormModal
          customer={null}
          prefill={choice?.mode === "new" ? choice.body : match.prefill}
          title="New customer from this invoice"
          onClose={() => setCustomerForm(false)}
          onSubmitDraft={(body) => {
            setChoice({ mode: "new", body });
            setCustomerForm(false);
          }}
        />
      )}
    </>
  );
}

function FieldInput(props: {
  id: string;
  label: string;
  type: string;
  raw: Raw;
  cell: Cell;
  issues: Check[];
  wide: boolean;
  disabled?: boolean;
  active: boolean;
  onFocus: () => void;
  onChange: (v: string) => void;
}) {
  const { id, label, type, raw, cell, issues, wide, disabled, active, onFocus, onChange } = props;
  const missing = raw == null;
  const low = !missing && cell.confidence != null && cell.confidence < 0.8 && !cell.edited;
  const norm = shown(type, cell.value);
  const err = issues.find((c) => c.severity === "error");
  return (
    <div className={cn("flex flex-col gap-1", wide && "sm:col-span-2")}>
      <label
        htmlFor={id}
        className="flex items-center justify-between gap-2 text-[13px] font-medium text-ink-2"
      >
        <span>{label}</span>
        {missing ? (
          <span className="text-xs font-normal text-subtle">Not on invoice</span>
        ) : cell.edited ? (
          <Tag tone="bl" size="sm">
            edited
          </Tag>
        ) : low ? (
          <Tag tone="md" size="sm">
            low confidence {pct(cell.confidence)}
          </Tag>
        ) : cell.confidence != null ? (
          <span className="text-xs font-normal text-subtle">{pct(cell.confidence)}</span>
        ) : null}
      </label>
      <input
        id={id}
        value={raw ?? ""}
        placeholder={missing ? "Not on invoice. Type to add." : undefined}
        disabled={disabled}
        onFocus={onFocus}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={err ? true : undefined}
        aria-describedby={issues.length ? `${id}-msg` : undefined}
        className={cn(
          "min-h-9 rounded-[10px] border border-line-input bg-white px-3 text-sm text-ink outline-none placeholder:text-subtle focus:border-primary focus:ring-2 focus:ring-bl-bg disabled:bg-surface",
          (type === "gstin" || type === "pan") && "font-mono",
          missing && "border-dashed",
          low && "border-md-line bg-md-bg",
          err ? "border-hi-line bg-hi-wash" : issues.length ? "border-md-line" : "",
          active && "ring-2 ring-primary",
        )}
      />
      {norm && raw && norm !== raw && <span className="text-xs text-muted">Read as {norm}</span>}
      {issues.map((c) => (
        <span
          key={c.id}
          id={`${id}-msg`}
          className={cn("text-xs", c.severity === "error" ? "text-hi" : "text-md")}
        >
          {c.severity === "error" ? "✕ " : "! "}
          {c.message}
        </span>
      ))}
    </div>
  );
}

function ChecksCard(props: {
  errors: Check[];
  warnings: Check[];
  acked: Set<string>;
  setAcked: (s: Set<string>) => void;
  onGo: (p: string) => void;
  editable: boolean;
}) {
  const { errors, warnings, acked, setAcked, onGo, editable } = props;
  if (!errors.length && !warnings.length)
    return (
      <div className="rounded-card border border-ok-line bg-ok-bg px-5 py-3 text-sm text-ok">
        ✓ All checks pass: line maths, totals, tax type, GSTINs, dates and amount in words agree.
      </div>
    );
  const allAcked = warnings.every((w) => acked.has(w.id));
  return (
    <Card accent={errors.length ? "hi" : "md"}>
      <CardHeader
        title="Checks"
        suffix={[
          errors.length && `${errors.length} must be fixed`,
          warnings.length && `${warnings.length} to review`,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <ul className="m-0 list-none border-t border-divider px-5 py-2">
        {[...errors, ...warnings].map((c) => (
          <li key={c.id} className="flex items-start gap-3 py-1.5 text-sm">
            {c.severity === "warning" && editable ? (
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                aria-label={`Accept: ${c.message}`}
                checked={acked.has(c.id)}
                onChange={(e) => {
                  const next = new Set(acked);
                  if (e.target.checked) next.add(c.id);
                  else next.delete(c.id);
                  setAcked(next);
                }}
              />
            ) : (
              <span
                aria-hidden
                className={cn(
                  "mt-1.5 size-2 flex-none rounded-full",
                  c.severity === "error" ? "bg-hi" : "bg-md-accent",
                )}
              />
            )}
            <span className="flex-1">
              <span className={c.severity === "error" ? "text-hi" : "text-ink-2"}>{c.message}</span>{" "}
              <button
                type="button"
                onClick={() => onGo(c.path)}
                className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-medium text-link"
              >
                Show
              </button>
            </span>
          </li>
        ))}
      </ul>
      {editable && warnings.length > 1 && (
        <label className="flex items-center gap-2.5 border-t border-divider px-5 py-2.5 text-[13px] text-ink-2">
          <input
            type="checkbox"
            className="size-4"
            checked={allAcked}
            onChange={(e) => setAcked(new Set(e.target.checked ? warnings.map((w) => w.id) : []))}
          />
          I've checked all {warnings.length} warnings against the invoice
        </label>
      )}
    </Card>
  );
}

function QrCard({ qr, checks }: { qr: Record<string, unknown>; checks: Check[] }) {
  const mismatches = checks.filter((c) => c.code === "qr_mismatch");
  if (qr.kind !== "gst_einvoice")
    return (
      <div className="rounded-card border border-line px-5 py-3 text-sm text-muted">
        A QR code was found, but it isn't a GST e-invoice QR.
      </div>
    );
  const total = qr.total_value_paise as number | null;
  return (
    <div
      className={cn(
        "rounded-card border px-5 py-3 text-sm",
        mismatches.length ? "border-md-line bg-md-bg" : "border-ok-line bg-ok-bg",
      )}
    >
      <b className={mismatches.length ? "text-md" : "text-ok"}>
        {mismatches.length
          ? `E-invoice QR differs from the invoice in ${mismatches.length} place${mismatches.length > 1 ? "s" : ""}`
          : "✓ E-invoice QR matches the invoice"}
      </b>
      <span className="block text-[13px] text-ink-2">
        Decoded from the QR (signed by the IRP): {String(qr.doc_no ?? "—")} ·{" "}
        {qr.doc_date ? longDate(String(qr.doc_date)) : "—"} ·{" "}
        {total != null ? `₹${rupees(total)}` : "—"} · seller {String(qr.seller_gstin ?? "—")} ·
        buyer {String(qr.buyer_gstin ?? "—")}
      </span>
    </div>
  );
}

function CustomerCard({
  match,
  choice,
  setChoice,
  onCreate,
}: {
  match: Match;
  choice: Choice;
  setChoice: (c: Choice) => void;
  onCreate: () => void;
}) {
  return (
    <Card>
      <CardHeader
        title="Customer"
        suffix={
          match.kind === "existing"
            ? "matched"
            : match.kind === "new"
              ? "not in your customers yet"
              : "needs your choice"
        }
      />
      <div className="flex flex-col gap-2 border-t border-divider px-5 py-4">
        <p className={cn("m-0 text-sm", match.kind === "ambiguous" ? "text-md" : "text-ink-2")}>
          {match.message}
        </p>
        {match.candidates.map((c) => (
          <label
            key={c.customer_id}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-xl border border-line px-3.5 py-3 text-sm",
              choice?.mode === "existing" &&
                choice.id === c.customer_id &&
                "border-primary bg-surface-blue shadow-[0_0_0_1px_var(--color-primary)]",
            )}
          >
            <input
              type="radio"
              name="customer"
              checked={choice?.mode === "existing" && choice.id === c.customer_id}
              onChange={() => setChoice({ mode: "existing", id: c.customer_id })}
            />
            <span className="flex flex-1 flex-col">
              <b className="font-semibold">{c.name}</b>
              <small className="text-xs text-muted">
                {c.gstin ? <span className="font-mono">{c.gstin}</span> : "No GSTIN"} ·{" "}
                {c.reasons.join(" · ")}
              </small>
            </span>
            {c.gstin_conflict && (
              <Tag tone="md" size="sm">
                different GSTIN
              </Tag>
            )}
            <Link
              to={`/orders/customers/${c.customer_id}`}
              target="_blank"
              className="text-[13px]"
              onClick={(e) => e.stopPropagation()}
            >
              View ↗
            </Link>
          </label>
        ))}
        <label
          className={cn(
            "flex cursor-pointer items-center gap-3 rounded-xl border border-line px-3.5 py-3 text-sm",
            choice?.mode === "new" &&
              "border-primary bg-surface-blue shadow-[0_0_0_1px_var(--color-primary)]",
          )}
        >
          <input
            type="radio"
            name="customer"
            checked={choice?.mode === "new"}
            onChange={onCreate}
          />
          <span className="flex flex-1 flex-col">
            <b className="font-semibold">
              {choice?.mode === "new"
                ? `New customer: ${choice.body.name}`
                : "Create a new customer"}
            </b>
            <small className="text-xs text-muted">
              {choice?.mode === "new"
                ? [choice.body.gstin, choice.body.phone, choice.body.email]
                    .filter(Boolean)
                    .join(" · ") || "Details from the invoice"
                : "Prefilled from the invoice's buyer details"}
            </small>
          </span>
          {choice?.mode === "new" && (
            <button
              type="button"
              onClick={onCreate}
              className="cursor-pointer border-0 bg-transparent text-[13px] font-medium text-link"
            >
              Edit details
            </button>
          )}
        </label>
      </div>
    </Card>
  );
}

function RejectModal({ uploadId, onClose }: { uploadId: string; onClose: () => void }) {
  const [reason, setReason] = useState("Not an invoice");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const reject = async () => {
    try {
      unwrap(
        await api.POST("/api/invoices/uploads/{upload_id}/reject", {
          params: { path: { upload_id: uploadId } },
          body: { reason },
        }),
      );
      await qc.invalidateQueries({ queryKey: ["invoices"] });
      toast({ title: "Upload rejected", tone: "default" });
      navigate("/orders/customers/imports");
    } catch (e) {
      toast({
        title: "Couldn't reject",
        description: e instanceof ApiError ? e.message : undefined,
        tone: "error",
      });
    }
  };
  return (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && onClose()}
      title="Reject this upload?"
      description="Nothing from it is saved. The file stays in the imports list as rejected."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Keep it
          </Button>
          <Button variant="danger" onClick={reject} disabled={reason.trim().length < 3}>
            Reject
          </Button>
        </>
      }
    >
      <TextAreaField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
    </Modal>
  );
}
