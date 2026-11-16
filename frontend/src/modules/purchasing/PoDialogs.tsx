import { useState } from "react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { addDays, isoDay } from "@/modules/planning/format";
import {
  qtyText,
  usePoAction,
  useRaisePo,
  type Inventory,
  type MaterialRow,
  type Po,
  type PoAction,
} from "./api";

const field = "w-full rounded-xl border border-line-input px-3.5 py-2.5 text-sm font-normal";
const lbl = "flex flex-col gap-1.5 text-[13px] font-medium text-ink-2";

/** Raise a PO for one material. It waits for the owner's approval before it counts as on order. */
export function RaisePoDialog({
  inventory,
  material,
  onClose,
}: {
  inventory: Inventory;
  material: MaterialRow | null;
  onClose: () => void;
}) {
  const raise = useRaisePo();
  const { toast } = useToast();
  const today = inventory.today;
  const [materialId, setMaterialId] = useState(material?.id ?? inventory.materials[0]?.id ?? "");
  const m = inventory.materials.find((x) => x.id === materialId);
  const [supplier, setSupplier] = useState(material?.supplier ?? "");
  const [qty, setQty] = useState(
    material && Number(material.suggested_qty) > 0 ? String(Number(material.suggested_qty)) : "",
  );
  const [price, setPrice] = useState(material ? String(material.price_per_unit_paise / 100) : "");
  const [due, setDue] = useState(
    material?.shortfall ? material.shortfall.needed_by : addDays(today, 7),
  );
  const [note, setNote] = useState("");
  const [orders, setOrders] = useState<string[]>(
    material?.shortfall ? [material.shortfall.number] : [],
  );
  const [priority, setPriority] = useState<"high" | "medium" | "low">("medium");
  const [err, setErr] = useState<string | null>(null);
  const pick = (id: string) => {
    setMaterialId(id);
    setOrders([]);
    const x = inventory.materials.find((r) => r.id === id);
    if (x) {
      setSupplier(x.supplier ?? "");
      setQty(Number(x.suggested_qty) > 0 ? String(Number(x.suggested_qty)) : "");
      setPrice(String(x.price_per_unit_paise / 100));
    }
  };
  const needs = m?.needs ?? [];
  const valid = !!m && supplier.trim() && Number(qty) > 0 && Number(price) >= 0 && due >= today;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Raise purchase order"
      description="It goes to the owner for approval; once approved it counts as on order and Planning sees the delivery."
      width={520}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!valid || raise.isPending}
            onClick={async () => {
              setErr(null);
              try {
                const po = await raise.mutateAsync({
                  material_id: materialId,
                  supplier: supplier.trim(),
                  quantity: qty,
                  price_per_unit_paise: Math.round(Number(price) * 100),
                  expected_date: due,
                  note: note.trim() || null,
                  order_numbers: orders,
                  priority: orders.length ? null : priority,
                });
                toast({
                  title: `${po.number} raised`,
                  description: "Awaiting the owner's approval",
                  tone: "success",
                });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't raise the PO.");
              }
            }}
          >
            Raise PO
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className={`${lbl} sm:col-span-2`}>
          Material
          <select className={field} value={materialId} onChange={(e) => pick(e.target.value)}>
            {inventory.materials.map((x) => (
              <option key={x.id} value={x.id}>
                {x.code} · {x.name}
              </option>
            ))}
          </select>
          {m && (
            <span className="font-normal text-muted">
              In stock {qtyText(m.in_stock, m.unit)} · reorder level{" "}
              {qtyText(m.reorder_level, m.unit)}
              {m.shortfall ? ` · ${m.reason}` : ""}
            </span>
          )}
        </label>
        <label className={`${lbl} sm:col-span-2`}>
          Supplier
          <input
            className={field}
            list="suppliers"
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
          />
          <datalist id="suppliers">
            {inventory.suppliers.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </label>
        <label className={lbl}>
          Quantity ({m?.unit})
          <input
            className={field}
            inputMode="decimal"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Price per {m?.unit} (₹)
          <input
            className={field}
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Needed by
          <input
            className={field}
            type="date"
            min={today}
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Note <span className="font-normal text-subtle">(optional)</span>
          <input className={field} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0 sm:col-span-2">
          <legend className="mb-1.5 text-[13px] font-medium text-ink-2">
            For orders <span className="font-normal text-subtle">(sets the PO's priority)</span>
          </legend>
          {needs.length === 0 ? (
            <span className="text-[13px] text-muted">No order needs this material right now.</span>
          ) : (
            needs.map((n) => (
              <label key={n.number} className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={orders.includes(n.number)}
                  onChange={(e) =>
                    setOrders(
                      e.target.checked
                        ? [...orders, n.number]
                        : orders.filter((x) => x !== n.number),
                    )
                  }
                />
                <b className="font-mono font-semibold">{n.number}</b> {n.customer} · needs{" "}
                {qtyText(n.qty, m?.unit ?? "")} by {n.needed_by}
              </label>
            ))
          )}
          {orders.length === 0 && (
            <label className="mt-1 flex items-center gap-2 text-[13px]">
              Priority
              <select
                aria-label="Priority"
                className="rounded-lg border border-line-input px-2 py-1 text-[13px]"
                value={priority}
                onChange={(e) => setPriority(e.target.value as typeof priority)}
              >
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          )}
        </fieldset>
        {err && (
          <p role="alert" className="m-0 text-sm text-hi sm:col-span-2">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

export type DialogAction = Exclude<PoAction, "approve">;

/** One step on a PO that needs input: supplier's date, dispatch, gate entry, QC, follow-up, cancel, edit. */
export function PoActionDialog({
  po,
  action,
  onClose,
}: {
  po: Po;
  action: DialogAction;
  onClose: () => void;
}) {
  const act = usePoAction();
  const { toast } = useToast();
  const line = po.lines[0]!;
  const left = Number(line.quantity) - Number(line.received_qty);
  const atGate = Number(po.gate_qty ?? 0);
  const [date, setDate] = useState(po.expected_date);
  const [qty, setQty] = useState(String(action === "qc" ? atGate : left));
  const [rejected, setRejected] = useState("0");
  const [text, setText] = useState("");
  const [ref, setRef] = useState("");
  const [supplier, setSupplier] = useState(po.supplier);
  const [price, setPrice] = useState(String(line.price_per_unit_paise / 100));
  const [err, setErr] = useState<string | null>(null);
  const today = isoDay(new Date());
  const acc = Number(qty);
  const rej = Number(rejected || 0);
  const meta: Record<DialogAction, { title: string; button: string; ok: boolean; done: string }> = {
    confirm: {
      title: `Supplier's date for ${po.number}`,
      button: "Save date",
      ok: !!date,
      done: `${po.number} · supplier confirmed ${date}`,
    },
    dispatch: {
      title: `${po.number} dispatched`,
      button: "Mark in transit",
      ok: !!date,
      done: `${po.number} in transit`,
    },
    "gate-entry": {
      title: `Gate entry for ${po.number}`,
      button: "Log gate entry",
      ok: acc > 0 && acc <= left && !!ref.trim(),
      done: `${po.number} at the gate · ready for QC`,
    },
    qc: {
      title: `QC for ${po.number}`,
      button: "Save QC",
      ok:
        acc >= 0 && rej >= 0 && Math.abs(acc + rej - atGate) < 1e-9 && (rej === 0 || !!text.trim()),
      done: `${qtyText(acc, line.unit)} accepted into stock`,
    },
    "follow-up": {
      title: `Follow up ${po.supplier}`,
      button: "Save follow-up",
      ok: !!text.trim(),
      done: `Follow-up saved on ${po.number}`,
    },
    cancel: {
      title: `Cancel ${po.number}?`,
      button: "Cancel PO",
      ok: !!text.trim(),
      done: `${po.number} cancelled`,
    },
    edit: {
      title: `Change ${po.number}`,
      button: "Save changes",
      ok: !!supplier.trim() && acc > 0 && Number(price) >= 0 && date >= today,
      done: `${po.number} changed`,
    },
  };
  const m = meta[action];
  const body = (): unknown => {
    switch (action) {
      case "confirm":
        return { expected_date: date };
      case "dispatch":
        return { expected_date: date, note: text.trim() || null };
      case "gate-entry":
        return { quantity: qty, reference: ref.trim(), note: text.trim() || null };
      case "qc":
        return { accepted: qty, rejected: rejected || "0", reason: text.trim() || null };
      case "follow-up":
        return {
          note: text.trim(),
          promised_date: date !== po.expected_date ? date : null,
        };
      case "edit":
        return {
          supplier: supplier.trim(),
          quantity: qty,
          price_per_unit_paise: Math.round(Number(price) * 100),
          expected_date: date,
        };
      default:
        return { reason: text.trim() };
    }
  };
  const dateField = (label: string) => (
    <label className={lbl}>
      {label}
      <input
        className={field}
        type="date"
        min={today}
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />
    </label>
  );
  const textField = (label: string, placeholder = "") => (
    <label className={lbl}>
      {label}
      <textarea
        rows={2}
        className={field}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    </label>
  );
  const qtyField = (label: string, hint: string) => (
    <label className={lbl}>
      {label} ({line.unit})
      <input
        className={field}
        inputMode="decimal"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
      />
      <span className="font-normal text-muted">{hint}</span>
    </label>
  );
  return (
    <Modal
      open
      tone={action === "cancel" ? "danger" : "default"}
      onOpenChange={(o) => !o && onClose()}
      title={m.title}
      description={`${qtyText(line.quantity, line.unit)} ${line.material} from ${po.supplier}`}
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={!m.ok || act.isPending}
            onClick={async () => {
              setErr(null);
              try {
                await act.mutateAsync({ id: po.id, action, body: body() });
                toast({ title: m.done, tone: "success" });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            {m.button}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {action === "confirm" && dateField("Delivery date the supplier confirmed")}
        {action === "dispatch" && (
          <>
            {dateField("Expected arrival")}
            {textField("Note (optional)", "e.g. LR no., transporter")}
          </>
        )}
        {action === "gate-entry" && (
          <>
            {qtyField(
              "Quantity at the gate",
              `${qtyText(left, line.unit)} still to come. Stock goes up only after QC.`,
            )}
            <label className={lbl}>
              Challan / vehicle no.
              <input
                className={field}
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                placeholder="e.g. CH-4471 / MH14 GT 2210"
              />
            </label>
            {textField("Note (optional)")}
          </>
        )}
        {action === "qc" && (
          <>
            <p className="m-0 text-[13px] text-muted">
              At the gate: {qtyText(atGate, line.unit)} · {po.gate_ref}. Accepted goes into stock;
              rejected goes back to {po.supplier} and is still owed.
            </p>
            {qtyField("Accepted", "Goes into stock")}
            <label className={lbl}>
              Rejected ({line.unit})
              <input
                className={field}
                inputMode="decimal"
                value={rejected}
                onChange={(e) => setRejected(e.target.value)}
              />
            </label>
            {rej > 0 && textField("Why rejected", "e.g. rusty coils, wrong grade")}
          </>
        )}
        {action === "follow-up" && (
          <>
            {textField("What the supplier said", "e.g. Called Mr Rao: truck leaves tomorrow")}
            {dateField("Delivery date they promise now")}
          </>
        )}
        {action === "cancel" && textField("Reason")}
        {action === "edit" && (
          <>
            <label className={lbl}>
              Supplier
              <input
                className={field}
                value={supplier}
                onChange={(e) => setSupplier(e.target.value)}
              />
            </label>
            {qtyField("Quantity", "Only while it waits for approval")}
            <label className={lbl}>
              Price per {line.unit} (₹)
              <input
                className={field}
                inputMode="decimal"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </label>
            {dateField("Needed by")}
          </>
        )}
        {err && (
          <p role="alert" className="m-0 text-sm text-hi">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}
