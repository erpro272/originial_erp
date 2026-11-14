import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button, Caret } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { useRanking, useSaveRanking, type Ranking } from "./api";

type Mode = Ranking["mode"];
type WeightKey = keyof NonNullable<Ranking["weights"]>;

const MODES: { value: Mode; label: string; hint: string }[] = [
  {
    value: "weighted",
    label: "Weighted mix",
    hint: "Combine the factors below with your own weights",
  },
  { value: "deadline", label: "Deadline", hint: "Soonest ship date first" },
  { value: "profit", label: "Profit", hint: "Highest profit first" },
  { value: "customer", label: "Customer", hint: "Key customers first" },
  { value: "requirement", label: "Requirement", hint: "Largest quantity first" },
  { value: "priority", label: "Order priority", hint: "High → medium → low, as set on each order" },
];
const DEFAULT_WEIGHTS: Record<WeightKey, number> = {
  requirement: 10,
  customer: 20,
  profit: 25,
  deadline: 30,
  priority: 15,
};

const WEIGHTS: { key: WeightKey; label: string }[] = [
  { key: "deadline", label: "Deadline" },
  { key: "profit", label: "Profit" },
  { key: "customer", label: "Customer" },
  { key: "requirement", label: "Requirement (quantity)" },
  { key: "priority", label: "Order priority" },
];

export function RankingSettingsButton() {
  const { can } = useAuth();
  const ranking = useRanking();
  const [open, setOpen] = useState(false);
  const mode = ranking.data?.mode ?? "weighted";
  const label = MODES.find((m) => m.value === mode)?.label ?? mode;
  if (!can("settings.write"))
    return <span className="text-[13px] text-muted">Ranked by: {label}</span>;
  return (
    <>
      <Button variant="pill" onClick={() => setOpen(true)} aria-label="Order ranking settings">
        Ranked by: {label} <Caret />
      </Button>
      {open && ranking.data && (
        <RankingModal initial={ranking.data} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

function RankingModal({ initial, onClose }: { initial: Ranking; onClose: () => void }) {
  const save = useSaveRanking();
  const { toast } = useToast();
  const [mode, setMode] = useState<Mode>(initial.mode ?? "weighted");
  const [w, setW] = useState<Record<WeightKey, number>>(initial.weights ?? DEFAULT_WEIGHTS);
  const total = Object.values(w).reduce((a, b) => a + b, 0);
  const submit = async () => {
    try {
      await save.mutateAsync({ mode, weights: w });
      toast({
        title: "Ranking updated",
        description: "The top 3 cards now use your settings.",
        tone: "success",
      });
      onClose();
    } catch (e) {
      toast({
        title: "Couldn't save",
        description: e instanceof ApiError ? e.message : undefined,
        tone: "error",
      });
    }
  };
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Order ranking"
      description="Choose how the three 'Needs attention' cards are picked from your open orders."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={save.isPending || (mode === "weighted" && total === 0)}
          >
            Save ranking
          </Button>
        </>
      }
    >
      <fieldset className="m-0 grid gap-2 border-0 p-0 sm:grid-cols-2">
        <legend className="sr-only">Rank by</legend>
        {MODES.map((m) => (
          <label
            key={m.value}
            className={cn(
              "flex cursor-pointer items-start gap-2.5 rounded-xl border border-line px-3.5 py-3",
              mode === m.value &&
                "border-primary bg-surface-blue shadow-[0_0_0_1px_var(--color-primary)]",
            )}
          >
            <input
              type="radio"
              name="mode"
              className="mt-0.5"
              checked={mode === m.value}
              onChange={() => setMode(m.value)}
            />
            <span className="flex flex-col gap-0.5">
              <b className="text-sm font-semibold">{m.label}</b>
              <small className="text-xs text-muted">{m.hint}</small>
            </span>
          </label>
        ))}
      </fieldset>
      {mode === "weighted" && (
        <div className="flex flex-col gap-3 rounded-xl border border-divider bg-surface px-4 py-3">
          {WEIGHTS.map(({ key, label }) => (
            <label key={key} className="grid grid-cols-[160px_1fr_48px] items-center gap-3 text-sm">
              <span className="text-ink-2">{label}</span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={w[key]}
                onChange={(e) => setW({ ...w, [key]: Number(e.target.value) })}
                aria-label={`${label} weight`}
              />
              <span className="text-right font-medium tabular-nums">
                {total ? Math.round((w[key] / total) * 100) : 0}%
              </span>
            </label>
          ))}
          {total === 0 && (
            <span className="text-xs text-hi">Give at least one factor some weight.</span>
          )}
        </div>
      )}
    </Modal>
  );
}
