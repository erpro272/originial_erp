import { useState } from "react";
import { Link } from "react-router-dom";
import { type OptKey, type Plan } from "./api";
import { OrderTimeline } from "./OrderTimeline";

/** Step 1: Selected orders. */
export function SelectedOrders({ plan }: { plan: Plan }) {
  const sel = plan.result.selection;
  const using = (sel.using ?? "own") as OptKey;
  // The timeline highlights the option in use, until the owner clicks another one.
  const [focus, setFocus] = useState<OptKey | null>(null);

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
    </section>
  );
}
