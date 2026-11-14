import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { OPT_LABEL, usePatchPlan, type OptKey, type Plan, type PlanPatch } from "./api";
import { plural } from "./format";
import { OptionsTable } from "./OptionsTable";
import { OrdersInPlan } from "./OrdersInPlan";
import { OrderTimeline } from "./OrderTimeline";

/** Step 1: Selected orders. Timeline, the orders, and the 3 selection options all read one plan. */
export function SelectedOrders({ plan }: { plan: Plan }) {
  const { can } = useAuth();
  const editable = can("planning.write");
  const sel = plan.result.selection;
  const patch = usePatchPlan(plan.id);
  const { toast } = useToast();
  const using = (sel.using ?? "own") as OptKey;
  // The timeline highlights the option in use, until the owner clicks another one.
  const [focus, setFocus] = useState<OptKey | null>(null);
  // Show the tick at once while the server recalculates.
  const [pending, setPending] = useState<string[] | null>(null);
  const ticked = pending ?? sel.selected;

  const run = async (body: PlanPatch, ok?: string) => {
    try {
      await patch.mutateAsync(body);
      if (ok) toast({ title: ok, tone: "success" });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't update the plan.",
        tone: "error",
      });
    }
  };
  const toggle = async (id: string, on: boolean) => {
    const next = on ? [...ticked, id] : ticked.filter((x) => x !== id);
    setPending(next);
    await run({ selected: next });
    setPending(null);
    setFocus(null);
  };

  return (
    <section className="flex flex-col gap-7">
      <div className="flex flex-col gap-1.5">
        <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Selected orders</h2>
        <p className="m-0 text-sm text-muted">
          Pulled from <Link to="/orders">Orders received</Link>. Add or remove orders to change the
          combination that gets planned.
        </p>
      </div>
      <OrderTimeline
        selection={sel}
        today={plan.result.schedule.today}
        focus={focus ?? using}
        onFocus={setFocus}
      />
      <OrdersInPlan
        selection={sel}
        ticked={ticked}
        editable={editable}
        busy={patch.isPending}
        onToggle={toggle}
      />
      <OptionsTable
        selection={sel}
        focus={focus ?? using}
        onFocus={setFocus}
        editable={editable}
        busy={patch.isPending}
        onUse={async (k) => {
          await run(
            { use_option: k },
            `Using ${OPT_LABEL[k].toLowerCase()} · timeline and table updated`,
          );
          setFocus(null);
        }}
      />
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-card border border-line bg-surface px-6 py-5">
        <div className="flex flex-col gap-1">
          <b className="text-base">Ready to plan {plural(ticked.length, "order")}</b>
          <span className="text-sm text-muted">
            Sequence, machine and labour load, materials and financials come in the next steps,
            which are being rebuilt.
          </span>
        </div>
        <Button disabled title="Next steps coming soon">
          Generate plan → <span className="font-normal">(coming soon)</span>
        </Button>
      </div>
    </section>
  );
}
