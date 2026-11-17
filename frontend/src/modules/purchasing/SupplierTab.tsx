import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { rupees, shortDate } from "@/lib/format";
import { addDays, isoDay } from "@/modules/planning/format";
import {
  qtyText,
  usePutScoring,
  useReplyQuote,
  useRequestQuotes,
  useSetPreferred,
  useSupplier,
  type Comparison,
  type Quote,
  type ScoringRules,
  type SupplierRow,
} from "./api";

const field = "w-full rounded-xl border border-line-input px-3.5 py-2.5 text-sm font-normal";
const lbl = "flex flex-col gap-1.5 text-[13px] font-medium text-ink-2";

const rate = (r: SupplierRow) =>
  r.rate_paise != null ? `₹${rupees(r.rate_paise)} / ${r.unit}` : "–";
const days = (n: number | null | undefined) =>
  n == null ? "–" : `${Number.isInteger(n) ? n : n.toFixed(1)} day${n === 1 ? "" : "s"}`;
const pct = (n: number | null | undefined) => (n == null ? "–" : `${n}%`);

export function Stars({ n }: { n: number }) {
  if (!n) return <span className="text-[13px] text-subtle">not rated</span>;
  return (
    <span aria-label={`${n} of 5 stars`} className="tracking-[0.1em] text-md">
      {"★".repeat(n)}
      <span className="text-faint">{"★".repeat(5 - n)}</span>
    </span>
  );
}

function Flags({ flags }: { flags: string[] }) {
  return (
    <>
      {flags.map((f) => (
        <Tag key={f} tone={f === "No history yet" ? "lo" : "hi"} size="sm">
          {f}
        </Tag>
      ))}
    </>
  );
}

/** Supplier comparison: recommended suppliers for a material, the scorecard, and quote requests. */
export function SupplierTab({
  d,
  rows,
  materialId,
}: {
  d: Comparison;
  rows: SupplierRow[];
  materialId: string | null;
}) {
  const [openSupplier, setOpenSupplier] = useState<SupplierRow | null>(null);
  const [comparing, setComparing] = useState<string | null>(null);
  const [replying, setReplying] = useState<Quote | null>(null);
  const mid = materialId ?? d.default_material_id;
  const mat = d.materials.find((m) => m.id === mid);
  const cards = mid ? (d.top[mid] ?? []) : [];

  const col = createColumnHelper<SupplierRow>();
  const columns = [
    col.accessor("supplier", {
      id: "supplier",
      header: "Supplier",
      meta: { label: "Supplier", alwaysVisible: true },
      cell: (c) => (
        <span className="flex items-center gap-2">
          {c.getValue()}
          {c.row.original.preferred && (
            <Tag tone="ok" size="sm">
              Selected
            </Tag>
          )}
        </span>
      ),
    }),
    col.accessor((r) => r.material, {
      id: "category",
      header: "Category",
      meta: { label: "Category" },
    }),
    col.accessor((r) => r.rate_paise ?? Number.MAX_SAFE_INTEGER, {
      id: "rate",
      header: "Unit rate",
      meta: { label: "Unit rate" },
      cell: (c) => (
        <span title={c.row.original.rate_source === "quote" ? "Valid quote" : "Last price paid"}>
          {rate(c.row.original)}
        </span>
      ),
    }),
    col.accessor((r) => r.lead_days ?? 999, {
      id: "lead",
      header: "Avg lead time",
      meta: { label: "Avg lead time" },
      cell: (c) => (
        <span title={c.row.original.lead_source === "actual" ? "Actual deliveries" : "Quoted"}>
          {days(c.row.original.lead_days)}
        </span>
      ),
    }),
    col.accessor((r) => r.on_time_pct ?? -1, {
      id: "on_time",
      header: "On-time %",
      meta: { label: "On-time %" },
      cell: (c) => pct(c.row.original.on_time_pct),
    }),
    col.accessor((r) => r.quality_score ?? -1, {
      id: "quality",
      header: "Quality score",
      meta: { label: "Quality score" },
      cell: (c) =>
        c.row.original.quality_score == null ? "–" : `${c.row.original.quality_score} / 10`,
    }),
    col.accessor("active_pos", {
      id: "active_pos",
      header: "Active POs",
      meta: { label: "Active POs", align: "right" },
    }),
    col.accessor((r) => r.overall ?? -1, {
      id: "rating",
      header: "Rating",
      meta: { label: "Rating" },
      cell: (c) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <Stars n={c.row.original.stars} />
          <Flags flags={c.row.original.flags.filter((f) => f !== "No history yet")} />
        </span>
      ),
    }),
    col.accessor((r) => r.overall ?? -1, {
      id: "overall",
      header: "Score",
      meta: { label: "Overall score", defaultHidden: true },
      cell: (c) => pct(c.row.original.overall),
    }),
    col.accessor((r) => r.defect_pct ?? -1, {
      id: "defect",
      header: "Defect rate",
      meta: { label: "Defect rate", defaultHidden: true },
      cell: (c) => pct(c.row.original.defect_pct),
    }),
    col.accessor("deliveries", {
      id: "deliveries",
      header: "Deliveries (12 m)",
      meta: { label: "Deliveries (12 months)", defaultHidden: true, align: "right" },
    }),
  ];

  return (
    <div className="flex flex-col gap-6">
      {mat && (
        <section aria-label="Top recommended vendors" className="flex flex-col gap-3">
          <h2 className="m-0 text-xs font-semibold tracking-[0.06em] text-muted uppercase">
            Top recommended vendors · {mat.name}
          </h2>
          {cards.length === 0 ? (
            <p className="m-0 text-sm text-muted">
              No supplier has a price for {mat.name} yet. Ask for quotes with + Request Quote.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {cards.map((c, i) => (
                <TopCard
                  key={c.row.supplier_id}
                  badges={c.badges}
                  pct={c.pct}
                  note={c.note}
                  row={c.row}
                  first={i === 0}
                  onCompare={() => setComparing(c.row.material_id)}
                />
              ))}
            </div>
          )}
          <ScoreRule rules={d.rules} />
        </section>
      )}
      <DataTable<SupplierRow>
        tableId="purchasing-suppliers"
        title="Supplier scorecard & price benchmark"
        columns={columns}
        data={rows}
        getRowId={(r) => `${r.supplier_id}-${r.material_id}`}
        onRowClick={(r) => setOpenSupplier(r)}
        empty={{
          title: "No suppliers to compare",
          description: "Suppliers appear once they quote or deliver a material.",
        }}
      />
      <QuotesList quotes={d.quotes} onReply={setReplying} />
      {openSupplier && (
        <SupplierWindow
          row={openSupplier}
          rows={d.rows.filter((r) => r.supplier_id === openSupplier.supplier_id)}
          onClose={() => setOpenSupplier(null)}
        />
      )}
      {comparing && (
        <CompareDialog
          rows={d.rows.filter((r) => r.material_id === comparing)}
          onClose={() => setComparing(null)}
        />
      )}
      {replying && <ReplyQuoteDialog quote={replying} onClose={() => setReplying(null)} />}
    </div>
  );
}

function SelectButton({ row, variant = "dark" }: { row: SupplierRow; variant?: "dark" | "pill" }) {
  const { can } = useAuth();
  const set = useSetPreferred();
  const { toast } = useToast();
  if (row.preferred)
    return (
      <Tag tone="ok" size="sm">
        Selected vendor
      </Tag>
    );
  if (!can("purchasing.write")) return null;
  return (
    <Button
      variant={variant}
      size="sm"
      disabled={set.isPending}
      onClick={async () => {
        try {
          await set.mutateAsync({ material_id: row.material_id, supplier_id: row.supplier_id });
          toast({
            title: `${row.supplier} selected for ${row.material}`,
            description: "Raise PO now pre-fills this supplier and its rate",
            tone: "success",
          });
        } catch (e) {
          toast({ title: e instanceof ApiError ? e.message : "Couldn't select.", tone: "error" });
        }
      }}
    >
      Select vendor
    </Button>
  );
}

function TopCard({
  badges,
  pct: p,
  note,
  row,
  first,
  onCompare,
}: {
  badges: string[];
  pct: number;
  note: string;
  row: SupplierRow;
  first: boolean;
  onCompare: () => void;
}) {
  const weak = /^(Sub-optimal|Higher rate|Often late|Quality issues)/.test(note);
  return (
    <article
      data-testid={`top-${row.supplier}`}
      className={cn(
        "flex flex-col gap-1.5 rounded-card border p-[18px]",
        first ? "border-ok-line bg-ok-bg" : "border-line bg-card",
      )}
    >
      <div className="flex flex-wrap justify-end gap-1.5">
        {badges.map((b, i) => (
          <Tag
            key={b}
            tone={b === "Best overall" ? "ok" : b === "Highest quality" ? "bl" : "md"}
            size="sm"
          >
            {b}
            {i === 0 ? ` · ${p}%` : ""}
          </Tag>
        ))}
      </div>
      <b className="text-[17px]">{row.supplier}</b>
      <span className="text-[13px] text-ink-2">
        Rate: {rate(row)} · Lead time: {days(row.lead_days)}
      </span>
      <span className="text-[13px] text-ink-2">
        On-time: {pct(row.on_time_pct)} · Defect rate: {pct(row.defect_pct)}
      </span>
      <div className="mt-2 flex min-h-9 items-center justify-between gap-2 border-t border-divider pt-3">
        <span className={cn("text-[13px]", weak ? "text-hi" : first ? "text-ok" : "text-muted")}>
          {note}
        </span>
        {first ? (
          <SelectButton row={row} />
        ) : (
          <Button variant="pill" size="sm" onClick={onCompare}>
            Compare
          </Button>
        )}
      </div>
    </article>
  );
}

/** Every supplier of one material side by side, with Select vendor on each. */
function CompareDialog({ rows, onClose }: { rows: SupplierRow[]; onClose: () => void }) {
  const sorted = [...rows].sort((a, b) => (b.overall ?? -1) - (a.overall ?? -1));
  const lines: [string, (r: SupplierRow) => React.ReactNode][] = [
    ["Overall score", (r) => pct(r.overall)],
    ["Rating", (r) => <Stars n={r.stars} />],
    ["Unit rate", (r) => `${rate(r)}${r.rate_source === "quote" ? " (quote)" : ""}`],
    ["Lead time", (r) => `${days(r.lead_days)}${r.lead_source === "quote" ? " (quoted)" : ""}`],
    ["On-time", (r) => pct(r.on_time_pct)],
    ["Defect rate", (r) => pct(r.defect_pct)],
    ["Quality score", (r) => (r.quality_score == null ? "–" : `${r.quality_score} / 10`)],
    ["Deliveries (12 months)", (r) => r.deliveries],
    ["Active POs", (r) => r.active_pos],
    ["Flags", (r) => (r.flags.length ? <Flags flags={r.flags} /> : "–")],
    ["", (r) => <SelectButton row={r} variant="pill" />],
  ];
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Compare suppliers · ${rows[0]?.material ?? ""}`}
      width={Math.min(980, 260 + 190 * sorted.length)}
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th />
              {sorted.map((r) => (
                <th key={r.supplier_id} className="px-3 py-2 text-left font-semibold">
                  {r.supplier}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map(([k, f]) => (
              <tr key={k} className="border-t border-divider">
                <th className="py-2 pr-3 text-left text-[13px] font-medium text-muted">{k}</th>
                {sorted.map((r) => (
                  <td key={r.supplier_id} className="px-3 py-2">
                    {f(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

function SupplierWindow({
  row,
  rows,
  onClose,
}: {
  row: SupplierRow;
  rows: SupplierRow[];
  onClose: () => void;
}) {
  const s = useSupplier(row.supplier_id);
  const d = s.data;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={row.supplier}
      description={`On-time ${pct(row.on_time_pct)} · defect rate ${pct(row.defect_pct)} · ${row.deliveries} deliveries in 12 months${row.flags.length ? ` · ${row.flags.join(", ")}` : ""}`}
      width={720}
    >
      {!d ? (
        <LoadingState label="Loading the supplier" />
      ) : (
        <div className="flex flex-col gap-5 text-sm">
          <section className="flex flex-col gap-1.5">
            <h3 className="m-0 text-sm font-semibold">Materials</h3>
            {rows.map((r) => (
              <span key={r.material_id}>
                {r.material}: {rate(r)} · lead time {days(r.lead_days)} · score {pct(r.overall)}
                {r.preferred ? " · selected vendor" : ""}
              </span>
            ))}
            {d.open_pos.length > 0 && (
              <span className="text-muted">Open POs: {d.open_pos.join(", ")}</span>
            )}
          </section>
          <section className="flex flex-col gap-1.5">
            <h3 className="m-0 text-sm font-semibold">Deliveries</h3>
            {d.deliveries.length === 0 ? (
              <span className="text-muted">No deliveries in the last 12 months.</span>
            ) : (
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    {["PO", "Material", "Committed", "At the gate", "", "Lead", "QC"].map(
                      (h, i) => (
                        <th key={i} className="py-1.5 pr-3 font-medium">
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {d.deliveries.map((x, i) => (
                    <tr key={i} className="border-t border-divider">
                      <td className="py-1.5 pr-3 font-mono">{x.po_number}</td>
                      <td className="py-1.5 pr-3">{x.material}</td>
                      <td className="py-1.5 pr-3">
                        {x.promised_date ? shortDate(x.promised_date) : "–"}
                      </td>
                      <td className="py-1.5 pr-3">{shortDate(x.arrived)}</td>
                      <td className="py-1.5 pr-3">
                        {x.on_time == null ? null : x.on_time ? (
                          <Tag tone="ok" size="sm">
                            On time
                          </Tag>
                        ) : (
                          <Tag tone="hi" size="sm">
                            Late
                          </Tag>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">{days(x.lead_days)}</td>
                      <td className="py-1.5 pr-3">
                        {x.accepted == null
                          ? "–"
                          : `${qtyText(x.accepted, x.unit)} ok${Number(x.rejected) ? ` · ${qtyText(x.rejected!, x.unit)} rejected` : ""}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          {d.quotes.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="m-0 text-sm font-semibold">Quotes</h3>
              {d.quotes.map((q) => (
                <span key={q.id}>{quoteText(q)}</span>
              ))}
            </section>
          )}
        </div>
      )}
    </Modal>
  );
}

function quoteText(q: Quote): string {
  return q.status === "requested"
    ? `${q.code} · asked ${shortDate(q.created_at)} · waiting for a reply`
    : `${q.code} · ₹${rupees(q.rate_paise ?? 0)} / ${q.unit} · ${days(q.lead_days)} · valid till ${q.valid_until ? shortDate(q.valid_until) : "–"}`;
}

function QuotesList({ quotes, onReply }: { quotes: Quote[]; onReply: (q: Quote) => void }) {
  const { can } = useAuth();
  if (quotes.length === 0) return null;
  return (
    <section aria-label="Quotes" className="overflow-hidden rounded-card border border-line">
      <div className="flex items-center justify-between px-5 py-4">
        <h3 className="m-0 text-[17px] font-semibold">Quotes</h3>
        <span className="text-[13px] text-muted">
          Valid quotes set the unit rate; record each supplier's reply when it comes
        </span>
      </div>
      <ul className="m-0 list-none p-0">
        {quotes.map((q) => (
          <li
            key={q.id}
            data-testid={`quote-${q.supplier}-${q.code}`}
            className="flex flex-wrap items-center justify-between gap-3 border-t border-divider px-5 py-3 text-sm"
          >
            <span>
              <b className="font-semibold">{q.supplier}</b> · {q.material} · {quoteText(q)}
            </span>
            {q.status === "requested" ? (
              can("purchasing.write") ? (
                <Button variant="pill" size="sm" onClick={() => onReply(q)}>
                  Record reply
                </Button>
              ) : (
                <Tag tone="md" size="sm">
                  Waiting
                </Tag>
              )
            ) : (
              <Tag tone="ok" size="sm">
                Received
              </Tag>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RequestQuoteDialog({ d, onClose }: { d: Comparison; onClose: () => void }) {
  const req = useRequestQuotes();
  const { toast } = useToast();
  const [materialId, setMaterialId] = useState(d.default_material_id ?? d.materials[0]?.id ?? "");
  const known = [
    ...new Set(d.rows.filter((r) => r.material_id === materialId).map((r) => r.supplier)),
  ];
  const [picked, setPicked] = useState<string[]>([]);
  const [others, setOthers] = useState("");
  const [qty, setQty] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const mat = d.materials.find((m) => m.id === materialId);
  const names = [
    ...picked,
    ...others
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean),
  ];
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Request quotes"
      description="Recorded here; contact the suppliers as usual and record each reply when it comes."
      width={520}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!materialId || names.length === 0 || req.isPending}
            onClick={async () => {
              setErr(null);
              try {
                await req.mutateAsync({
                  material_id: materialId,
                  suppliers: names,
                  quantity: qty ? qty : null,
                  note: note.trim() || null,
                });
                toast({
                  title: `Quote requested from ${names.length} supplier${names.length === 1 ? "" : "s"}`,
                  tone: "success",
                });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            Request quotes
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className={lbl}>
          Material
          <select
            className={field}
            value={materialId}
            onChange={(e) => {
              setMaterialId(e.target.value);
              setPicked([]);
            }}
          >
            {d.materials.map((m) => (
              <option key={m.id} value={m.id}>
                {m.code} · {m.name}
              </option>
            ))}
          </select>
        </label>
        {known.length > 0 && (
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium text-ink-2">
              Suppliers of this material
            </legend>
            {known.map((n) => (
              <label key={n} className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={picked.includes(n)}
                  onChange={(e) =>
                    setPicked(e.target.checked ? [...picked, n] : picked.filter((x) => x !== n))
                  }
                />
                {n}
              </label>
            ))}
          </fieldset>
        )}
        <label className={lbl}>
          Other suppliers <span className="font-normal text-subtle">(comma-separated)</span>
          <input className={field} value={others} onChange={(e) => setOthers(e.target.value)} />
        </label>
        <label className={lbl}>
          Quantity ({mat?.unit}) <span className="font-normal text-subtle">(optional)</span>
          <input
            className={field}
            inputMode="decimal"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Note <span className="font-normal text-subtle">(optional)</span>
          <input className={field} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {err && (
          <p role="alert" className="m-0 text-sm text-hi">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

function ReplyQuoteDialog({ quote, onClose }: { quote: Quote; onClose: () => void }) {
  const reply = useReplyQuote();
  const { toast } = useToast();
  const today = isoDay(new Date());
  const [price, setPrice] = useState("");
  const [lead, setLead] = useState("");
  const [valid, setValid] = useState(addDays(today, 15));
  const [err, setErr] = useState<string | null>(null);
  const ok = Number(price) > 0 && lead !== "" && Number(lead) >= 0 && valid >= today;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Quote from ${quote.supplier}`}
      description={`${quote.material}${quote.quantity ? ` · ${qtyText(quote.quantity, quote.unit)}` : ""}`}
      width={440}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={!ok || reply.isPending}
            onClick={async () => {
              setErr(null);
              try {
                await reply.mutateAsync({
                  id: quote.id,
                  body: {
                    rate_paise: Math.round(Number(price) * 100),
                    lead_days: Number(lead),
                    valid_until: valid,
                  },
                });
                toast({ title: `Quote from ${quote.supplier} saved`, tone: "success" });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            Save quote
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className={lbl}>
          Rate per {quote.unit} (₹)
          <input
            className={field}
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Lead time (days)
          <input
            className={field}
            inputMode="numeric"
            value={lead}
            onChange={(e) => setLead(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Valid until
          <input
            className={field}
            type="date"
            min={today}
            value={valid}
            onChange={(e) => setValid(e.target.value)}
          />
        </label>
        {err && (
          <p role="alert" className="m-0 text-sm text-hi">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

/** How "Best overall" is worked out: the owner's weights and risk thresholds (company rule). */
function ScoreRule({ rules }: { rules: ScoringRules }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const editable = can("settings.write");
  return (
    <p className="m-0 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
      Score: price {rules.price_weight}% · on-time {rules.on_time_weight}% · quality{" "}
      {rules.quality_weight}% · lead time {rules.lead_weight}%. Late risk below{" "}
      {rules.late_risk_below}% on time; quality risk above {rules.quality_risk_above}% rejected.
      {editable && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link hover:underline"
        >
          Change
        </button>
      )}
      {open && <ScoreRuleDialog rules={rules} onClose={() => setOpen(false)} />}
    </p>
  );
}

function ScoreRuleDialog({ rules, onClose }: { rules: ScoringRules; onClose: () => void }) {
  const put = usePutScoring();
  const { toast } = useToast();
  const [v, setV] = useState<ScoringRules>(rules);
  const [err, setErr] = useState<string | null>(null);
  const fields: [keyof ScoringRules, string][] = [
    ["price_weight", "Price weight"],
    ["on_time_weight", "On-time weight"],
    ["quality_weight", "Quality weight"],
    ["lead_weight", "Lead time weight"],
    ["late_risk_below", "Late risk below (% on time)"],
    ["quality_risk_above", "Quality risk above (% rejected)"],
  ];
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Supplier score"
      description="How Best overall is worked out. Weights are relative: they don't have to add up to 100."
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={put.isPending}
            onClick={async () => {
              setErr(null);
              try {
                await put.mutateAsync(v);
                toast({ title: "Supplier score saved · suppliers re-rated", tone: "success" });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(([k, label]) => (
          <label key={k} className={lbl}>
            {label}
            <input
              className={field}
              inputMode="decimal"
              defaultValue={String(v[k])}
              onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })}
            />
          </label>
        ))}
        {err && (
          <p role="alert" className="m-0 text-sm text-hi sm:col-span-2">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}
