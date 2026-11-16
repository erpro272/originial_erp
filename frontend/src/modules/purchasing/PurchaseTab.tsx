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
import { generatedLabel } from "@/modules/planning/format";
import {
  PRIORITY,
  STAGE,
  qtyText,
  usePo,
  usePoAction,
  type Po,
  type PoDetail,
  type Purchases,
} from "./api";
import { PoActionDialog, type DialogAction } from "./PoDialogs";

const ATTENTION: Partial<Record<Po["stage"], { tag: string; tone: "hi" | "md" | "bl" }>> = {
  pending_approval: { tag: "Action required", tone: "hi" },
  delayed: { tag: "Delayed", tone: "hi" },
  arriving_today: { tag: "Arriving today", tone: "bl" },
  at_gate: { tag: "Arriving today", tone: "bl" },
};

function material(po: Po): string {
  const ln = po.lines[0];
  return ln ? `${ln.material} · ${qtyText(ln.quantity, ln.unit)}` : "–";
}

/** Raw Material Purchase: POs that need attention, then every PO. A PO opens with its timeline and next step. */
export function PurchaseTab({
  d,
  rows,
  open,
  onOpen,
}: {
  d: Purchases;
  rows: Po[];
  open: string | null;
  onOpen: (id: string | null) => void;
}) {
  const col = createColumnHelper<Po>();
  const columns = [
    col.accessor("number", {
      id: "number",
      header: "PO number",
      meta: { label: "PO number", alwaysVisible: true },
      cell: (c) => <b className="font-mono font-semibold">{c.getValue()}</b>,
    }),
    col.accessor("supplier", { id: "supplier", header: "Supplier", meta: { label: "Supplier" } }),
    col.accessor((r) => r.lines[0]?.material ?? "", {
      id: "material",
      header: "Material",
      meta: { label: "Material" },
    }),
    col.accessor((r) => r.orders.join(", "), {
      id: "orders",
      header: "Linked order",
      meta: { label: "Linked order" },
      cell: (c) => c.getValue() || "–",
    }),
    col.accessor((r) => Number(r.lines[0]?.quantity ?? 0), {
      id: "qty",
      header: "Qty",
      meta: { label: "Qty", align: "right" },
      cell: (c) => {
        const ln = c.row.original.lines[0];
        return ln ? qtyText(ln.quantity, ln.unit) : "–";
      },
    }),
    col.accessor("value_paise", {
      id: "amount",
      header: "Amount (₹)",
      meta: { label: "Amount", align: "right" },
      cell: (c) => rupees(c.getValue()),
    }),
    col.accessor("expected_date", {
      id: "expected",
      header: "Expected",
      meta: { label: "Expected" },
      cell: (c) => shortDate(c.getValue()),
    }),
    col.accessor("stage", {
      id: "status",
      header: "Status",
      meta: { label: "Status" },
      cell: (c) => (
        <Tag tone={STAGE[c.getValue()].tone} size="sm">
          {STAGE[c.getValue()].label}
        </Tag>
      ),
    }),
    col.accessor("priority", {
      id: "priority",
      header: "Priority",
      meta: { label: "Priority", defaultHidden: true },
      cell: (c) => PRIORITY[c.getValue()].label,
    }),
    col.accessor("needed_by", {
      id: "needed",
      header: "Needed by",
      meta: { label: "Needed by", defaultHidden: true },
      cell: (c) => (c.getValue() ? shortDate(c.getValue()!) : "–"),
    }),
  ];
  return (
    <div className="flex flex-col gap-6">
      {d.attention.length > 0 && (
        <section aria-label="Needs attention" className="flex flex-col gap-3">
          <h2 className="m-0 text-xs font-semibold tracking-[0.06em] text-muted uppercase">
            Needs attention
          </h2>
          <div className="grid gap-4 md:grid-cols-3">
            {d.attention.map((po) => (
              <AttentionCard key={po.id} po={po} onOpen={() => onOpen(po.id)} />
            ))}
          </div>
        </section>
      )}
      <DataTable<Po>
        tableId="purchasing-pos"
        title="All purchase orders"
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        onRowClick={(r) => onOpen(r.id)}
        empty={{
          title: "No purchase orders",
          description: "Raise one with + New PO, or from a shortage on the Inventory tab.",
        }}
      />
      {open && <PoWindow id={open} onClose={() => onOpen(null)} />}
    </div>
  );
}

function AttentionCard({ po, onOpen }: { po: Po; onOpen: () => void }) {
  const a = ATTENTION[po.stage]!;
  const { can } = useAuth();
  const [dialog, setDialog] = useState<DialogAction | null>(null);
  const write = can("purchasing.write");
  return (
    <article
      data-testid={`card-${po.number}`}
      className={cn(
        "flex flex-col gap-1.5 rounded-card border bg-white p-[18px]",
        po.stage === "pending_approval"
          ? "border-hi-line"
          : po.stage === "delayed"
            ? "border-md-line"
            : "border-line",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="cursor-pointer border-0 bg-transparent p-0 font-mono text-[13px] text-ink-2 hover:underline"
        >
          {po.number}
        </button>
        <Tag tone={a.tone} size="sm">
          {a.tag}
        </Tag>
      </div>
      <b className="text-[15px]">{material(po)}</b>
      <span className="text-[13px] text-ink-2">
        Supplier: {po.supplier}
        {po.orders.length ? ` · Linked: ${po.orders.join(", ")}` : ""}
      </span>
      <span className="text-[13px] text-ink-2">
        Amount: ₹{rupees(po.value_paise)} ·{" "}
        {po.stage === "pending_approval"
          ? `Delivery: ${shortDate(po.expected_date)}`
          : po.stage_text}
      </span>
      <div className="mt-2 flex min-h-9 items-center justify-between gap-2 border-t border-divider pt-3">
        {po.stage === "pending_approval" ? (
          <>
            <span className="text-[13px] text-muted">{PRIORITY[po.priority].label} priority</span>
            <ApproveButton po={po} />
          </>
        ) : po.stage === "delayed" ? (
          <>
            <button
              type="button"
              disabled={!write}
              onClick={() => setDialog("follow-up")}
              className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-hi hover:underline disabled:cursor-default disabled:no-underline"
            >
              Follow up vendor
            </button>
            <span className="text-[13px] text-muted">expected {shortDate(po.expected_date)}</span>
          </>
        ) : po.stage === "at_gate" ? (
          <>
            <span className="text-[13px] text-ok">Ready for QC</span>
            {write && (
              <Button variant="dark" size="sm" onClick={() => setDialog("qc")}>
                QC
              </Button>
            )}
          </>
        ) : (
          <>
            <span className="text-[13px] text-bl">Due today</span>
            {write && (
              <Button variant="dark" size="sm" onClick={() => setDialog("gate-entry")}>
                Gate entry
              </Button>
            )}
          </>
        )}
      </div>
      {dialog && <PoActionDialog po={po} action={dialog} onClose={() => setDialog(null)} />}
    </article>
  );
}

/** Owner: approve. Everyone else sees that the owner approves. */
export function ApproveButton({ po, size = "sm" }: { po: Po; size?: "sm" | "md" }) {
  const { can } = useAuth();
  const act = usePoAction();
  const { toast } = useToast();
  if (!can("purchasing.approve"))
    return <span className="text-[13px] text-subtle">Owner approves</span>;
  return (
    <Button
      variant="dark"
      size={size}
      disabled={act.isPending}
      onClick={async () => {
        try {
          await act.mutateAsync({ id: po.id, action: "approve" });
          toast({ title: `${po.number} approved · sent to ${po.supplier}`, tone: "success" });
        } catch (e) {
          toast({ title: e instanceof ApiError ? e.message : "Couldn't approve.", tone: "error" });
        }
      }}
    >
      Approve PO
    </Button>
  );
}

/** Which steps a PO can take next (the API refuses anything else). */
function nextSteps(po: Po): DialogAction[] {
  switch (po.status) {
    case "awaiting_approval":
      return ["edit", "cancel"];
    case "ordered":
    case "confirmed":
      return ["confirm", "dispatch", "gate-entry", "follow-up", "cancel"];
    case "dispatched":
      return ["gate-entry", "follow-up", "confirm", "cancel"];
    case "at_gate":
      return ["qc"];
    default:
      return [];
  }
}

const STEP_LABEL: Record<DialogAction, string> = {
  edit: "Edit",
  confirm: "Supplier's date",
  dispatch: "Dispatched",
  "gate-entry": "Gate entry",
  qc: "QC",
  "follow-up": "Follow up vendor",
  cancel: "Cancel PO",
};

function PoWindow({ id, onClose }: { id: string; onClose: () => void }) {
  const po = usePo(id);
  const { can } = useAuth();
  const [dialog, setDialog] = useState<DialogAction | null>(null);
  const p = po.data;
  const write = can("purchasing.write");
  return (
    <>
      <Modal
        open={!dialog}
        onOpenChange={(o) => !o && onClose()}
        title={p ? `${p.number} · ${p.supplier}` : "Purchase order"}
        description={p ? p.stage_text : undefined}
        width={640}
        footer={
          p && (write || p.status === "awaiting_approval") ? (
            <div className="flex w-full flex-wrap justify-end gap-2">
              {write &&
                nextSteps(p).map((a) => (
                  <Button
                    key={a}
                    variant={a === "cancel" ? "pill" : a === nextSteps(p)[0] ? "primary" : "pill"}
                    className={a === "cancel" ? "text-hi" : undefined}
                    onClick={() => setDialog(a)}
                  >
                    {STEP_LABEL[a]}
                  </Button>
                ))}
              {p.status === "awaiting_approval" && <ApproveButton po={p} size="md" />}
            </div>
          ) : undefined
        }
      >
        {!p ? <LoadingState label="Loading the PO" /> : <PoFacts po={p} />}
      </Modal>
      {/* outside the PO window, which hides while a step is being filled in */}
      {dialog && p && <PoActionDialog po={p} action={dialog} onClose={() => setDialog(null)} />}
    </>
  );
}

function PoFacts({ po }: { po: PoDetail }) {
  const ln = po.lines[0];
  const facts: [string, string][] = [
    ["Status", STAGE[po.stage].label],
    ["Material", ln ? `${ln.code} · ${ln.material}` : "–"],
    ["Quantity", ln ? qtyText(ln.quantity, ln.unit) : "–"],
    [
      "Received (QC passed)",
      ln
        ? `${qtyText(ln.received_qty, ln.unit)}${Number(ln.rejected_qty) ? ` · rejected ${qtyText(ln.rejected_qty, ln.unit)}` : ""}`
        : "–",
    ],
    ["Amount", `₹${rupees(po.value_paise)}`],
    ["Expected", `${shortDate(po.expected_date)}${po.confirmed ? " · supplier confirmed" : ""}`],
    ["Linked orders", po.orders.join(", ") || "–"],
    ["Priority", PRIORITY[po.priority].label],
    ["Needed by", po.needed_by ? shortDate(po.needed_by) : "–"],
  ];
  return (
    <div className="flex flex-col gap-5">
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-2.5 text-sm sm:grid-cols-3">
        {facts.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="m-0 font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      {po.note && <p className="m-0 text-[13px] text-muted">Note: {po.note}</p>}
      <section aria-label="Timeline" className="flex flex-col gap-2">
        <h3 className="m-0 text-sm font-semibold">Timeline</h3>
        <ol className="m-0 flex list-none flex-col gap-2 border-l border-line p-0 pl-4">
          {po.events.map((e, i) => (
            <li key={i} className="text-[13px]">
              <span className="text-ink">{e.summary}</span>
              <span className="text-muted">
                {" "}
                · {generatedLabel(e.at)}
                {e.by ? ` · ${e.by}` : ""}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
