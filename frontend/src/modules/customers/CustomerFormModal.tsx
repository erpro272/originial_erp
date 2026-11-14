import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError, api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { SelectField, TextAreaField, TextField } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { paiseToInput, parseRupeesToPaise } from "@/lib/format";
import { gstinError, STATES } from "@/lib/gst";
import type { CustomerDetail, CustomerIn } from "./api";

const opt = <T extends z.ZodType>(s: T) => s.optional().or(z.literal(""));
const schema = z
  .object({
    name: z.string().trim().min(2, "Enter the customer's name"),
    gstin: z.string().trim().toUpperCase(),
    pan: opt(
      z
        .string()
        .trim()
        .toUpperCase()
        .regex(/^[A-Z]{5}[0-9]{4}[A-Z]$/, "PAN looks like AAACT2727Q"),
    ),
    state_code: z.string(),
    phone: z.string().trim().max(32),
    email: opt(z.email("Enter a valid email")),
    payment_terms_days: z.string().regex(/^\d{0,3}$/, "Days, e.g. 30"),
    credit_limit: z
      .string()
      .refine((v) => !v.trim() || parseRupeesToPaise(v) !== null, "Amount, e.g. 5000000"),
    tier: z.enum(["key", "standard", "occasional"]),
    tags: z.string(),
    address: z.string().max(300),
    city: z.string().max(100),
    pincode: opt(z.string().regex(/^\d{6}$/, "6 digits")),
    contact_name: z.string().max(200),
    contact_phone: z.string().max(32),
    contact_email: opt(z.email("Enter a valid email")),
    bank_name: z.string().max(120),
    bank_ifsc: opt(
      z
        .string()
        .trim()
        .toUpperCase()
        .regex(/^[A-Z]{4}0[A-Z0-9]{6}$/, "IFSC looks like HDFC0001234"),
    ),
    bank_account: opt(
      z
        .string()
        .trim()
        .regex(/^\d{6,18}$/, "6–18 digits"),
    ),
    upi_id: opt(
      z
        .string()
        .trim()
        .regex(/^[\w.-]{2,}@[a-zA-Z]{2,}$/, "UPI looks like name@bank"),
    ),
    notes: z.string().max(4000),
  })
  .superRefine((v, ctx) => {
    const gErr = gstinError(v.gstin);
    if (gErr) ctx.addIssue({ code: "custom", path: ["gstin"], message: gErr });
    if (v.gstin && !gErr) {
      if (v.pan && v.pan !== v.gstin.slice(2, 12))
        ctx.addIssue({
          code: "custom",
          path: ["pan"],
          message: `Doesn't match the GSTIN (${v.gstin.slice(2, 12)})`,
        });
      if (v.state_code && v.state_code !== v.gstin.slice(0, 2))
        ctx.addIssue({
          code: "custom",
          path: ["state_code"],
          message: `GSTIN is for ${STATES[v.gstin.slice(0, 2)]}`,
        });
    }
  });
type Form = z.input<typeof schema>;

function toForm(c: CustomerDetail | null, p?: Partial<CustomerIn>): Form {
  const r = c?.row;
  const bill =
    c?.addresses.find((a) => a.kind === "billing") ??
    p?.addresses?.find((a) => a.kind === "billing");
  const contact = c?.contacts[0] ?? p?.contacts?.[0];
  return {
    name: r?.name ?? p?.name ?? "",
    gstin: r?.gstin ?? p?.gstin ?? "",
    pan: r?.pan ?? p?.pan ?? "",
    state_code: r?.state_code ?? p?.state_code ?? "",
    phone: r?.phone ?? p?.phone ?? "",
    email: r?.email ?? p?.email ?? "",
    payment_terms_days: r?.payment_terms_days?.toString() ?? "",
    credit_limit: r?.credit_limit_paise != null ? paiseToInput(r.credit_limit_paise) : "",
    tier: r?.tier ?? "standard",
    tags: (r?.tags ?? []).join(", "),
    address: bill?.line1 ?? "",
    city: bill?.city ?? "",
    pincode: bill?.pincode ?? "",
    contact_name: contact?.name ?? "",
    contact_phone: contact?.phone ?? "",
    contact_email: contact?.email ?? "",
    bank_name: c?.bank_name ?? "",
    bank_ifsc: c?.bank_ifsc ?? "",
    bank_account: "",
    upi_id: "",
    notes: c?.notes ?? "",
  };
}

function toBody(v: Form, editing: boolean): CustomerIn {
  const n = (s?: string) => (s && s.trim() ? s.trim() : null);
  const body: CustomerIn = {
    name: v.name.trim(),
    gstin: n(v.gstin),
    pan: n(v.pan),
    state_code: n(v.state_code),
    phone: n(v.phone),
    email: n(v.email),
    payment_terms_days: v.payment_terms_days ? Number(v.payment_terms_days) : null,
    credit_limit_paise: parseRupeesToPaise(v.credit_limit),
    tier: v.tier,
    tags: v.tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean),
    notes: n(v.notes),
    bank_name: n(v.bank_name),
    bank_ifsc: n(v.bank_ifsc),
    addresses: v.address.trim()
      ? [
          {
            kind: "billing",
            line1: v.address.trim(),
            city: n(v.city),
            state_code: n(v.state_code),
            pincode: n(v.pincode),
          },
        ]
      : [],
    contacts: v.contact_name.trim()
      ? [
          {
            name: v.contact_name.trim(),
            phone: n(v.contact_phone),
            email: n(v.contact_email),
            is_primary: true,
          },
        ]
      : [],
  };
  // Blank sensitive fields on edit mean "leave unchanged" (they are never sent back to the browser).
  if (!editing || v.bank_account) body.bank_account = n(v.bank_account);
  if (!editing || v.upi_id) body.upi_id = n(v.upi_id);
  return body;
}

export function CustomerFormModal({
  customer,
  prefill,
  onClose,
  onSaved,
  onSubmitDraft,
  title,
}: {
  customer: CustomerDetail | null;
  prefill?: Partial<CustomerIn>;
  onClose: () => void;
  onSaved?: (id: string) => void;
  /** Invoice flow: return the details instead of saving (saved with the invoice in one go). */
  onSubmitDraft?: (body: CustomerIn) => void;
  title?: string;
}) {
  const editing = customer !== null;
  const qc = useQueryClient();
  const { toast } = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: toForm(customer, prefill),
    mode: "onBlur",
  });

  const submit = async (v: Form) => {
    setServerError(null);
    const body = toBody(v, editing);
    if (onSubmitDraft) return onSubmitDraft(body);
    try {
      const res = editing
        ? unwrap(
            await api.PATCH("/api/customers/{customer_id}", {
              params: { path: { customer_id: customer.row.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/customers", { body }));
      await qc.invalidateQueries({ queryKey: ["customers"] });
      toast({ title: editing ? "Customer saved" : `${body.name} added`, tone: "success" });
      onSaved?.(res.id);
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        const fields = (e.details.fields ?? {}) as Record<string, string>;
        Object.entries(fields).forEach(([k, msg]) => setError(k as keyof Form, { message: msg }));
        if (!Object.keys(fields).length) setServerError(e.message);
        else if (e.status === 409) setServerError(e.message);
      } else setServerError("Couldn't save. Check your connection and try again.");
    }
  };

  const sens = customer?.sensitive_visible ?? true;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      width={760}
      title={title ?? (editing ? `Edit ${customer.row.name}` : "Add customer")}
      description={
        prefill
          ? "Prefilled from the invoice. Check the details before continuing."
          : "GSTIN fills PAN and state automatically when saved."
      }
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="customer-form" disabled={isSubmitting}>
            {onSubmitDraft ? "Use these details" : editing ? "Save changes" : "Add customer"}
          </Button>
        </>
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
      <form
        id="customer-form"
        noValidate
        onSubmit={handleSubmit(submit)}
        className="grid gap-4 sm:grid-cols-2"
      >
        <div className="sm:col-span-2">
          <TextField label="Name" error={errors.name?.message} {...register("name")} />
        </div>
        <TextField
          label="GSTIN"
          className="font-mono uppercase"
          error={errors.gstin?.message}
          {...register("gstin")}
        />
        <TextField
          label="PAN"
          className="font-mono uppercase"
          error={errors.pan?.message}
          {...register("pan")}
        />
        <SelectField label="State" error={errors.state_code?.message} {...register("state_code")}>
          <option value="">—</option>
          {Object.entries(STATES).map(([code, name]) => (
            <option key={code} value={code}>
              {code} · {name}
            </option>
          ))}
        </SelectField>
        <SelectField label="Tier" {...register("tier")}>
          <option value="key">Key account</option>
          <option value="standard">Standard</option>
          <option value="occasional">Occasional</option>
        </SelectField>
        <TextField label="Phone" type="tel" error={errors.phone?.message} {...register("phone")} />
        <TextField
          label="Email"
          type="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <TextField
          label="Payment terms (days)"
          inputMode="numeric"
          error={errors.payment_terms_days?.message}
          {...register("payment_terms_days")}
        />
        <TextField
          label="Credit limit (₹)"
          inputMode="decimal"
          error={errors.credit_limit?.message}
          {...register("credit_limit")}
        />
        <div className="sm:col-span-2">
          <TextField
            label="Billing address"
            error={errors.address?.message}
            {...register("address")}
          />
        </div>
        <TextField label="City" {...register("city")} />
        <TextField
          label="PIN code"
          inputMode="numeric"
          error={errors.pincode?.message}
          {...register("pincode")}
        />
        <TextField label="Contact person" {...register("contact_name")} />
        <TextField label="Contact phone" type="tel" {...register("contact_phone")} />
        <TextField
          label="Contact email"
          type="email"
          error={errors.contact_email?.message}
          {...register("contact_email")}
        />
        <TextField
          label="Tags"
          hint="Comma-separated, e.g. automotive, export"
          {...register("tags")}
        />
        {sens && (
          <>
            <TextField label="Bank name" {...register("bank_name")} />
            <TextField
              label="IFSC"
              className="font-mono uppercase"
              error={errors.bank_ifsc?.message}
              {...register("bank_ifsc")}
            />
            <TextField
              label="Bank account number"
              inputMode="numeric"
              autoComplete="off"
              hint={
                editing
                  ? `Stored encrypted${customer.bank_account ? ` (${customer.bank_account})` : ""}. Leave blank to keep it.`
                  : "Stored encrypted."
              }
              error={errors.bank_account?.message}
              {...register("bank_account")}
            />
            <TextField
              label="UPI ID"
              autoComplete="off"
              hint={editing ? "Leave blank to keep the current one." : undefined}
              error={errors.upi_id?.message}
              {...register("upi_id")}
            />
          </>
        )}
        <div className="sm:col-span-2">
          <TextAreaField label="Notes" {...register("notes")} />
        </div>
      </form>
    </Modal>
  );
}
