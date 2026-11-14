import { useState } from "react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { shortDate } from "@/lib/format";
import { previewPatch, usePatchPlan, type Plan, type PlanPatch, type Preview } from "./api";
import { plural } from "./format";

/**
 * Reorder / bar-edge moves: the server simulates the change first (nothing saved).
 * Worse bottlenecks or deliveries -> warning popup (Cancel keeps the old order).
 * Only better -> applied with a small toast. Hard blocks (locked slot, before material) -> refused.
 */
export function useReorder(plan: Plan) {
  const patch = usePatchPlan(plan.id);
  const { toast } = useToast();
  const [pending, setPending] = useState<{
    body: PlanPatch;
    label: string;
    diff: Preview["diff"];
  } | null>(null);
  const num = (id: string) => plan.result.selection.orders[id]?.number ?? id;

  const commit = async (body: PlanPatch, better: number) => {
    try {
      const r = await patch.mutateAsync(body);
      toast({
        title: better ? `Reordered · ${plural(better, "bottleneck")} cleared` : "Plan updated",
        description: r.tabs.length ? `${plural(r.tabs.length, "tab")} changed` : undefined,
        tone: "success",
      });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't apply that change.",
        tone: "error",
      });
    }
  };

  const request = async (body: PlanPatch, label: string) => {
    let pv: Preview;
    try {
      pv = await previewPatch(plan.id, body);
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't check that change.",
        tone: "error",
      });
      return;
    }
    if (pv.diff.blocked) {
      toast({ title: pv.diff.blocked, tone: "error" });
      return;
    }
    if (pv.diff.warn) setPending({ body, label, diff: pv.diff });
    else await commit(body, pv.diff.better.length);
  };

  const modal = pending && (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && setPending(null)}
      title={
        <>
          Moving <span className="font-mono">{pending.label}</span>{" "}
          {pending.diff.worse.length ? "creates bottlenecks" : "makes a delivery late"}
        </>
      }
      description="Here's what changes if you continue."
      footer={
        <>
          <Button variant="pill" onClick={() => setPending(null)}>
            Cancel, keep old order
          </Button>
          <Button
            disabled={patch.isPending}
            onClick={async () => {
              const p = pending;
              setPending(null);
              await commit(p.body, p.diff.better.length);
            }}
          >
            Continue anyway
          </Button>
        </>
      }
    >
      <div className="flex flex-col">
        {pending.diff.worse.map((b) => (
          <div
            key={`${b.kind}${b.resource}`}
            className="flex gap-3 border-t border-divider py-3 text-sm"
          >
            <span className="mt-1.5 size-2 flex-none rounded-full bg-hi" />
            <div>
              <b className="block">{b.title}</b>
              <small className="text-[13px] text-muted">
                {b.text}
                {b.was ? ` (was ${b.was})` : ""}
                {b.orders.length ? ` · ${b.orders.map(num).join(", ")}` : ""}
              </small>
            </div>
          </div>
        ))}
        {pending.diff.deliveries.length > 0 && (
          <div className="flex gap-3 border-t border-divider py-3 text-sm">
            <span className="mt-1.5 size-2 flex-none rounded-full bg-hi" />
            <div>
              <b className="block">Deliveries</b>
              <small className="text-[13px] text-muted">
                {pending.diff.deliveries
                  .map((d) =>
                    Number(d.now) === 0
                      ? `${num(String(d.id))} now on time`
                      : `${num(String(d.id))} finishes ${shortDate(String(d.finish))} (${plural(Number(d.now), "day")} late)`,
                  )
                  .join(" · ")}
              </small>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );

  return { request, modal, busy: patch.isPending };
}
