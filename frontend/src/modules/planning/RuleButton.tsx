import { useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tooltip } from "@/components/ui/Menu";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { rupees } from "@/lib/format";
import { usePutRules, useRules, type Rules } from "./api";

export type RuleKey = "penalty" | "min_margin" | "overhead" | "packaging";

const RULES: Record<RuleKey, { title: string; help: string }> = {
  penalty: {
    title: "Late-delivery penalty",
    help: "What a late delivery costs you per day late. Used for penalties at risk and to weigh fixes.",
  },
  min_margin: {
    title: "Minimum margin",
    help: "Plans below this contribution margin are flagged on the approval checklist.",
  },
  overhead: {
    title: "Factory overheads",
    help: "Added on top of materials, labour and machine cost (rent, supervision, utilities).",
  },
  packaging: {
    title: "Packaging & logistics",
    help: "Cost per piece for packing and dispatch.",
  },
};

/** Small comment icon next to a number that is the company's own choice; opens a dialog to set it. */
export function RuleButton({ rule }: { rule: RuleKey }) {
  const { can } = useAuth();
  const rules = useRules();
  const [open, setOpen] = useState(false);
  const meta = RULES[rule];
  const editable = can("settings.write");
  const icon = (
    <button
      type="button"
      aria-label={`${meta.title}: ${editable ? "set your rule" : "set by the owner"}`}
      onClick={() => editable && setOpen(true)}
      className={cn(
        "inline-grid size-5 place-items-center rounded-full border-0 bg-transparent p-0 align-middle text-subtle",
        editable ? "cursor-pointer hover:bg-bl-bg hover:text-bl" : "cursor-help",
      )}
    >
      <svg
        aria-hidden
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
  return (
    <>
      <Tooltip
        content={
          editable
            ? `${meta.title}: your rule. Click to change.`
            : `${meta.title}: set by the owner.`
        }
      >
        {icon}
      </Tooltip>
      {open && rules.data && (
        <RuleDialog rule={rule} rules={rules.data} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

function RuleDialog({
  rule,
  rules,
  onClose,
}: {
  rule: RuleKey;
  rules: Rules;
  onClose: () => void;
}) {
  const meta = RULES[rule];
  const put = usePutRules();
  const { toast } = useToast();
  const [v, setV] = useState<Rules>(rules);
  const [err, setErr] = useState<string | null>(null);
  const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
  const save = async () => {
    setErr(null);
    try {
      await put.mutateAsync(v);
      toast({ title: `${meta.title} saved · plan recalculated`, tone: "success" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save.");
    }
  };
  const field = "w-full rounded-xl border border-line-input px-3.5 py-2.5 text-sm";
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={meta.title}
      description={meta.help}
      width={440}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={put.isPending}>
            Save
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {rule === "penalty" && (
          <>
            <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
              <legend className="mb-1 text-[13px] font-medium text-ink-2">
                How is it charged?
              </legend>
              {(["fixed", "percent"] as const).map((m) => (
                <label key={m} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="penalty_mode"
                    checked={v.penalty_mode === m}
                    onChange={() => setV({ ...v, penalty_mode: m })}
                  />
                  {m === "fixed"
                    ? "A fixed amount per day late"
                    : "A % of the order value per day late"}
                </label>
              ))}
            </fieldset>
            {v.penalty_mode === "fixed" ? (
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
                ₹ per day late
                <input
                  className={field}
                  inputMode="numeric"
                  defaultValue={(v.penalty_fixed_paise ?? 0) / 100}
                  onChange={(e) =>
                    setV({ ...v, penalty_fixed_paise: Math.round(num(e.target.value) * 100) })
                  }
                />
                <span className="font-normal text-muted">
                  Now {`₹${rupees(v.penalty_fixed_paise ?? 0)}`} a day
                </span>
              </label>
            ) : (
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
                % of order value per day late
                <input
                  className={field}
                  inputMode="decimal"
                  defaultValue={v.penalty_percent}
                  onChange={(e) => setV({ ...v, penalty_percent: num(e.target.value) })}
                />
              </label>
            )}
          </>
        )}
        {rule === "min_margin" && (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
            Minimum contribution margin (%)
            <input
              className={field}
              inputMode="decimal"
              defaultValue={v.min_margin_pct}
              onChange={(e) => setV({ ...v, min_margin_pct: num(e.target.value) })}
            />
          </label>
        )}
        {rule === "overhead" && (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
            Overheads (% of materials + labour + machine)
            <input
              className={field}
              inputMode="decimal"
              defaultValue={v.overhead_pct}
              onChange={(e) => setV({ ...v, overhead_pct: num(e.target.value) })}
            />
          </label>
        )}
        {rule === "packaging" && (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
            ₹ per piece
            <input
              className={field}
              inputMode="decimal"
              defaultValue={(v.packaging_paise_per_unit ?? 0) / 100}
              onChange={(e) =>
                setV({ ...v, packaging_paise_per_unit: Math.round(num(e.target.value) * 100) })
              }
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
