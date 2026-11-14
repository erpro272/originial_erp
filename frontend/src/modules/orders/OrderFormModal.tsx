import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { SelectField, TextAreaField, TextField } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { longDate, paiseToInput, parseRupeesToPaise, qty, rupees } from "@/lib/format";
import {
  NEXT_STATUSES,
  ORDER_STATUS_LABEL,
  useCustomerOptions,
  useInvalidateOrders,
  useProducts,
  type Order,
} from "./api";

const money = z
  .string()
  .trim()
  .refine(
    (v) => parseRupeesToPaise(v) !== null && parseRupeesToPaise(v)! >= 0,
    "Enter an amount like 1250.50",
  );

const schema = z.object({
  customer_id: z.string().min(1, "Choose a customer"),
  product_id: z.string().min(1, "Choose a product"),
  quantity: z
    .string()
    .trim()
    .refine(
      (v) => /^\d+(\.\d{1,3})?$/.test(v.replace(/,/g, "")) && Number(v.replace(/,/g, "")) > 0,
      "Enter a quantity above 0",
    ),
  unit_price: money,
  unit_cost: money,
  processing_days: z.coerce.number().int().min(1, "At least 1 day").max(365),
  ship_date: z.string().min(1, "Choose a ship date"),
  priority: z.enum(["high", "medium", "low"]),
  status: z.string(),
  progress_pct: z.string().optional(),
  marked_for_planning: z.boolean(),
  notes: z.string().max(2000).optional(),
});
type Form = z.input<typeof schema>;

export function OrderFormModal({ order, onClose }: { order: Order | null; onClose: () => void }) {
  const customers = useCustomerOptions();
  const products = useProducts();
  // Native selects need their options before the saved value can be selected.
  if (!customers.data || !products.data) {
    return (
      <Modal open onOpenChange={(o) => !o && onClose()} title={order ? order.number : "New order"}>
        <LoadingState label="Loading…" />
      </Modal>
    );
  }
  return <OrderForm order={order} onClose={onClose} />;
}

function OrderForm({ order, onClose }: { order: Order | null; onClose: () => void }) {
  const isNew = order === null;
  const { can } = useAuth();
  const readOnly =
    !can("orders.write") || (!isNew && ["shipped", "cancelled"].includes(order.status));
  const customers = useCustomerOptions();
  const products = useProducts();
  const invalidate = useInvalidateOrders();
  const { toast } = useToast();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    setError,
    formState: { errors, isSubmitting, dirtyFields },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: order
      ? {
          customer_id: order.customer_id,
          product_id: order.product_id,
          quantity: String(Number(order.quantity)),
          unit_price: paiseToInput(order.unit_price_paise),
          unit_cost: paiseToInput(order.unit_cost_paise),
          processing_days: order.processing_days,
          ship_date: order.ship_date,
          priority: order.priority,
          status: order.status,
          progress_pct: order.progress_pct?.toString() ?? "",
          marked_for_planning: order.marked_for_planning,
          notes: order.notes ?? "",
        }
      : {
          priority: "medium",
          status: "new",
          marked_for_planning: false,
          processing_days: 3,
          quantity: "",
          unit_price: "",
          unit_cost: "",
          ship_date: "",
          customer_id: "",
          product_id: "",
        },
  });

  const status = watch("status");
  const q = Number((watch("quantity") ?? "").replace(/,/g, "")) || 0;
  const price = parseRupeesToPaise(watch("unit_price") ?? "") ?? 0;
  const cost = parseRupeesToPaise(watch("unit_cost") ?? "") ?? 0;
  const sales = Math.round(q * price);
  const profit = sales - Math.round(q * cost);

  const onProduct = (id: string) => {
    const p = products.data?.find((x) => x.id === id);
    if (!p) return;
    if (!watch("unit_price")) setValue("unit_price", paiseToInput(p.unit_price_paise));
    setValue("unit_cost", paiseToInput(p.unit_cost_paise));
    setValue("processing_days", p.processing_days);
  };

  const statusOptions = isNew
    ? (["new", "accepted"] as const)
    : [order.status, ...NEXT_STATUSES[order.status]];

  const submit = async (v: Form) => {
    setServerError(null);
    const body = {
      customer_id: v.customer_id,
      product_id: v.product_id,
      quantity: v.quantity.replace(/,/g, ""),
      unit_price_paise: parseRupeesToPaise(v.unit_price)!,
      unit_cost_paise: parseRupeesToPaise(v.unit_cost)!,
      processing_days: Number(v.processing_days),
      ship_date: v.ship_date,
      priority: v.priority,
      notes: v.notes || null,
    };
    try {
      if (isNew) {
        const o = unwrap(
          await api.POST("/api/orders", {
            body: { ...body, status: v.status as "new" | "accepted" },
          }),
        );
        toast({ title: `${o.number} created`, tone: "success" });
      } else {
        // Send only what changed, so untouched money figures are never recalculated.
        const d = dirtyFields;
        const patch = {
          customer_id: d.customer_id ? body.customer_id : undefined,
          product_id: d.product_id ? body.product_id : undefined,
          quantity: d.quantity ? body.quantity : undefined,
          unit_price_paise: d.unit_price ? body.unit_price_paise : undefined,
          unit_cost_paise: d.unit_cost ? body.unit_cost_paise : undefined,
          processing_days: d.processing_days ? body.processing_days : undefined,
          ship_date: d.ship_date ? body.ship_date : undefined,
          priority: d.priority ? body.priority : undefined,
          notes: d.notes ? body.notes : undefined,
          status: v.status !== order.status ? (v.status as Order["status"]) : undefined,
          progress_pct:
            v.status === "in_production" && v.progress_pct ? Number(v.progress_pct) : undefined,
          marked_for_planning: v.status === "accepted" ? v.marked_for_planning : undefined,
        };
        unwrap(
          await api.PATCH("/api/orders/{order_id}", {
            params: { path: { order_id: order.id } },
            body: patch,
          }),
        );
        toast({ title: `${order.number} saved`, tone: "success" });
      }
      await invalidate();
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        const field = e.details.field as keyof Form | undefined;
        if (field) setError(field, { message: e.message });
        else setServerError(e.message);
      } else setServerError("Couldn't save. Check your connection and try again.");
    }
  };

  return (
    <>
      <Modal
        open
        onOpenChange={(o) => !o && onClose()}
        width={720}
        title={
          isNew ? (
            "New order"
          ) : (
            <span className="flex items-center gap-3">
              <span className="font-mono">{order.number}</span>
              <Tag tone={order.signal.tone}>{order.signal.label}</Tag>
            </span>
          )
        }
        description={
          isNew
            ? "Orders start as New. Accept them to send them to Planning."
            : `Created ${longDate(order.created_at)}`
        }
        footer={
          !readOnly && (
            <div className="flex w-full flex-wrap items-center justify-between gap-2">
              <span>
                {!isNew && ["new", "accepted", "planned"].includes(order.status) && (
                  <Button
                    variant="ghost"
                    className="text-hi hover:bg-hi-bg hover:text-hi"
                    onClick={() => setCancelOpen(true)}
                  >
                    Cancel order
                  </Button>
                )}
              </span>
              <span className="flex gap-2.5">
                <Button variant="pill" onClick={onClose}>
                  Close
                </Button>
                <Button type="submit" form="order-form" disabled={isSubmitting}>
                  {isSubmitting ? "Saving…" : isNew ? "Create order" : "Save changes"}
                </Button>
              </span>
            </div>
          )
        }
      >
        {serverError && (
          <div
            role="alert"
            className="rounded-xl border border-hi-line bg-hi-wash px-3.5 py-2.5 text-sm text-hi"
          >
            {serverError}
          </div>
        )}
        {!isNew && order.status === "cancelled" && (
          <p className="m-0 text-sm text-muted">Cancelled: {order.cancel_reason}</p>
        )}
        <form
          id="order-form"
          noValidate
          onSubmit={handleSubmit(submit)}
          className="grid gap-4 sm:grid-cols-2"
        >
          <fieldset disabled={readOnly} className="contents">
            <SelectField
              label="Customer"
              error={errors.customer_id?.message}
              {...register("customer_id")}
            >
              <option value="">Choose…</option>
              {customers.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Product"
              error={errors.product_id?.message}
              {...register("product_id", { onChange: (e) => onProduct(e.target.value) })}
            >
              <option value="">Choose…</option>
              {products.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.sku})
                </option>
              ))}
            </SelectField>
            <TextField
              label="Quantity (pcs)"
              inputMode="decimal"
              error={errors.quantity?.message}
              {...register("quantity")}
            />
            <TextField
              label="Ship date"
              type="date"
              error={errors.ship_date?.message}
              {...register("ship_date")}
            />
            <TextField
              label="Unit price (₹)"
              inputMode="decimal"
              error={errors.unit_price?.message}
              {...register("unit_price")}
            />
            <TextField
              label="Unit cost (₹)"
              inputMode="decimal"
              hint="Filled from the product; change it for this order if needed."
              error={errors.unit_cost?.message}
              {...register("unit_cost")}
            />
            <TextField
              label="Processing time (days)"
              type="number"
              min={1}
              error={errors.processing_days?.message}
              {...register("processing_days")}
            />
            <SelectField label="Priority" {...register("priority")}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </SelectField>
            <SelectField label="Status" error={errors.status?.message} {...register("status")}>
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {ORDER_STATUS_LABEL[s]}
                </option>
              ))}
            </SelectField>
            {status === "in_production" ? (
              <TextField
                label="Progress (%)"
                type="number"
                min={0}
                max={100}
                {...register("progress_pct")}
              />
            ) : (
              <label className="flex items-center gap-2.5 self-end pb-2.5 text-sm text-ink-2">
                <input
                  type="checkbox"
                  className="size-4"
                  disabled={status !== "accepted"}
                  {...register("marked_for_planning")}
                />
                Send to Planning{" "}
                {status !== "accepted" && (
                  <span className="text-xs text-subtle">(accepted orders only)</span>
                )}
              </label>
            )}
            <div className="sm:col-span-2">
              <TextAreaField label="Notes" {...register("notes")} />
            </div>
          </fieldset>
        </form>
        <div className="grid grid-cols-3 overflow-hidden rounded-xl border border-divider bg-surface text-sm">
          {[
            ["Sales", `₹${rupees(sales)}`],
            ["Profit", `₹${rupees(profit)}`],
            ["Margin", sales ? `${((profit / sales) * 100).toFixed(1)}%` : "—"],
          ].map(([k, v], i) => (
            <div key={k} className={i ? "border-l border-divider px-4 py-2.5" : "px-4 py-2.5"}>
              <span className="block text-xs text-muted">{k}</span>
              <b className="tabular-nums">{v}</b>
            </div>
          ))}
        </div>
        {!isNew && order.materials.length > 0 && (
          <div className="text-[13px] text-muted">
            Material:{" "}
            {order.materials.map((m) => (
              <span key={m.code} className="mr-3">
                {m.name} {qty(m.required)} {m.unit}
                {Number(m.shortage) > 0 && (
                  <b className="text-md">
                    {" "}
                    · {qty(m.shortage)} {m.unit} short
                  </b>
                )}
              </span>
            ))}
          </div>
        )}
      </Modal>
      {cancelOpen && order && (
        <CancelOrderModal
          order={order}
          onClose={() => setCancelOpen(false)}
          onDone={() => {
            setCancelOpen(false);
            onClose();
          }}
        />
      )}
    </>
  );
}

function CancelOrderModal({
  order,
  onClose,
  onDone,
}: {
  order: Order;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const invalidate = useInvalidateOrders();
  const { toast } = useToast();
  const submit = async () => {
    if (reason.trim().length < 3) return setError("Give a short reason (at least 3 characters).");
    setBusy(true);
    try {
      unwrap(
        await api.POST("/api/orders/{order_id}/cancel", {
          params: { path: { order_id: order.id } },
          body: { reason },
        }),
      );
      toast({ title: `${order.number} cancelled`, tone: "success" });
      await invalidate();
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel the order.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && onClose()}
      title={`Cancel ${order.number}?`}
      description="The order moves to Past orders. This can't be undone."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Keep order
          </Button>
          <Button variant="danger" onClick={submit} disabled={busy}>
            Cancel order
          </Button>
        </>
      }
    >
      <TextAreaField
        label="Reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={error ?? undefined}
        autoFocus
      />
    </Modal>
  );
}
