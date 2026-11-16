import { useState } from "react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { isoDay, addDays } from "@/modules/planning/format";
import { qtyText, usePoAction, useRaisePo, type Inventory, type MaterialRow, type Po } from "./api";

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
  const [err, setErr] = useState<string | null>(null);
  const pick = (id: string) => {
    setMaterialId(id);
    const x = inventory.materials.find((r) => r.id === id);
    if (x) {
      setSupplier(x.supplier ?? "");
      setQty(Number(x.suggested_qty) > 0 ? String(Number(x.suggested_qty)) : "");
      setPrice(String(x.price_per_unit_paise / 100));
    }
  };
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
        {err && (
          <p role="alert" className="m-0 text-sm text-hi sm:col-span-2">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

/** Confirm (supplier's date) / Receive (quantity) / Cancel (reason) one PO. */
export function PoActionDialog({
  po,
  action,
  onClose,
}: {
  po: Po;
  action: "confirm" | "receive" | "cancel";
  onClose: () => void;
}) {
  const act = usePoAction();
  const { toast } = useToast();
  const line = po.lines[0]!;
  const left = Number(line.quantity) - Number(line.received_qty);
  const [date, setDate] = useState(po.expected_date);
  const [qty, setQty] = useState(String(left));
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const meta = {
    confirm: {
      title: `Supplier confirmed ${po.number}`,
      button: "Save confirmed date",
      ok: !!date,
    },
    receive: {
      title: `Receive ${po.number}`,
      button: "Record receipt",
      ok: Number(qty) > 0 && Number(qty) <= left,
    },
    cancel: { title: `Cancel ${po.number}?`, button: "Cancel PO", ok: !!reason.trim() },
  }[action];
  return (
    <Modal
      open
      tone={action === "cancel" ? "danger" : "default"}
      onOpenChange={(o) => !o && onClose()}
      title={meta.title}
      description={`${qtyText(line.quantity, line.unit)} ${line.material} from ${po.supplier}`}
      width={440}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={!meta.ok || act.isPending}
            onClick={async () => {
              setErr(null);
              try {
                const body =
                  action === "confirm"
                    ? { expected_date: date }
                    : action === "receive"
                      ? { line_id: line.id, quantity: qty }
                      : { reason: reason.trim() };
                const out = await act.mutateAsync({ id: po.id, action, body });
                toast({
                  title:
                    action === "receive"
                      ? `${qtyText(qty, line.unit)} received · ${out.status === "received" ? "PO complete" : "rest still to come"}`
                      : action === "confirm"
                        ? `${po.number} confirmed`
                        : `${po.number} cancelled`,
                  tone: "success",
                });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            {meta.button}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {action === "confirm" && (
          <label className={lbl}>
            Delivery date the supplier confirmed
            <input
              className={field}
              type="date"
              min={isoDay(new Date())}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        )}
        {action === "receive" && (
          <label className={lbl}>
            Quantity received ({line.unit})
            <input
              className={field}
              inputMode="decimal"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
            <span className="font-normal text-muted">
              {qtyText(left, line.unit)} still to come. Stock goes up by what you record.
            </span>
          </label>
        )}
        {action === "cancel" && (
          <label className={lbl}>
            Reason
            <textarea
              rows={3}
              className={field}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
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
