import { useState } from "react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { shortDate } from "@/lib/format";
import { previewPatch, usePatchPlan, type Plan, type PlanPatch, type Preview } from "./api";
import { hrs, plural, range } from "./format";

/**
 * Reorder / finish-date moves on the schedule (owner's choice: warn first, as the mockup).
 * The server simulates the change (nothing saved). Worse bottlenecks or deliveries -> popup
 * (Cancel keeps the old order). Only better -> applied with a small toast. Hard blocks
 * (a locked slot, before the plan start, before the material arrives) -> refused.
 * Returns true when the change was applied.
 */
export function useReorder(plan: Plan) {
  const patch = usePatchPlan(plan.id);
  const { toast } = useToast();
  const [pending, setPending] = useState<{
    body: PlanPatch;
    label: string;
    action?: string;
    diff: Preview["diff"];
    done: (ok: boolean) => void;
  } | null>(null);
  const num = (id: string) => plan.result.selection.orders[id]?.number ?? id;

  const commit = async (body: PlanPatch, better: number): Promise<boolean> => {
    try {
      const r = await patch.mutateAsync(body);
      toast({
        title: better ? `Reordered · ${plural(better, "bottleneck")} cleared` : "Schedule updated",
        description: r.tabs.length ? `${plural(r.tabs.length, "step")} updated` : undefined,
        tone: "success",
      });
      return true;
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't apply that change.",
        tone: "error",
      });
      return false;
    }
  };

  /** `action` words the popup title, e.g. "Finishing ORD-1044 on Wed 25 Nov" (default "Moving ORD-1044"). */
  const request = async (body: PlanPatch, label: string, action?: string): Promise<boolean> => {
    let pv: Preview;
    try {
      pv = await previewPatch(plan.id, body);
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't check that change.",
        tone: "error",
      });
      return false;
    }
    if (pv.diff.blocked) {
      toast({ title: pv.diff.blocked, tone: "error" });
      return false;
    }
    if (!pv.diff.warn) return commit(body, pv.diff.better.length);
    return new Promise<boolean>((done) => setPending({ body, label, action, diff: pv.diff, done }));
  };

  const close = (ok: boolean) => {
    pending?.done(ok);
    setPending(null);
  };

  const deliveries = pending?.diff.deliveries ?? [];
  const modal = pending && (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && close(false)}
      title={
        <>
          {pending.action ?? (
            <>
              Moving <span className="font-mono">{pending.label}</span>
            </>
          )}{" "}
          {pending.diff.worse.length ? "creates bottlenecks" : "makes a delivery late"}
        </>
      }
      description="Here's what changes if you continue."
      footer={
        <>
          <Button variant="pill" onClick={() => close(false)}>
            Cancel, keep old order
          </Button>
          <Button
            disabled={patch.isPending}
            onClick={async () => {
              const p = pending;
              setPending(null);
              p.done(await commit(p.body, p.diff.better.length));
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
              <b className="block">
                {b.kind === "constraint" || b.kind === "machine"
                  ? `${b.resource} over capacity · ${range(b.from, b.to)}`
                  : b.title}
              </b>
              <small className="text-[13px] text-muted">
                {b.kind === "constraint" || b.kind === "machine" ? `+${hrs(b.size)}` : b.text}
                {b.was ? ` (was ${b.was})` : ""}
                {b.orders.length ? ` · ${b.orders.map(num).join(", ")}` : ""}
              </small>
            </div>
          </div>
        ))}
        {deliveries.length > 0 && (
          <div className="flex gap-3 border-t border-divider py-3 text-sm">
            <span className="mt-1.5 size-2 flex-none rounded-full bg-hi" />
            <div>
              <b className="block">Deliveries</b>
              <small className="text-[13px] text-muted">
                {deliveries
                  .map((d) =>
                    Number(d.now) === 0
                      ? `${num(String(d.id))} now on time`
                      : `${num(String(d.id))} slips to ${shortDate(String(d.finish))} (${plural(Number(d.now), "day")} late)`,
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
