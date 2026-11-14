import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

type Rules = Schemas["HealthSettings"];
const FIELDS: { key: keyof Rules; label: string; hint: string }[] = [
  {
    key: "repeat_min_invoices",
    label: "Repeat: at least N purchases",
    hint: "…and bought within the 'recent' window",
  },
  { key: "repeat_recent_days", label: "Repeat: bought within (days)", hint: "" },
  {
    key: "inactive_days",
    label: "Inactive after (days)",
    hint: "Previously regular, no purchase since",
  },
  { key: "dormant_days", label: "Dormant after (days)", hint: "No purchase since" },
  {
    key: "high_value_top_pct",
    label: "High-value: top % by sales",
    hint: "Of customers who bought in the period",
  },
  {
    key: "declining_drop_pct",
    label: "Declining: sales down by (%)",
    hint: "Compared with the previous period",
  },
];

export function HealthSettingsModal({ initial, onClose }: { initial: Rules; onClose: () => void }) {
  const [v, setV] = useState<Rules>(initial);
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const { toast } = useToast();
  const save = async () => {
    try {
      unwrap(await api.PUT("/api/customers/health-settings", { body: v }));
      await qc.invalidateQueries({ queryKey: ["customers"] });
      toast({ title: "Health rules updated", tone: "success" });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save.");
    }
  };
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Customer health rules"
      description="New = first purchase within the period. A customer can have several tags; the table shows the most urgent."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save}>Save rules</Button>
        </>
      }
    >
      {error && (
        <p role="alert" className="m-0 text-sm text-hi">
          {error}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <TextField
            key={f.key}
            label={f.label}
            hint={f.hint || undefined}
            type="number"
            min={1}
            value={v[f.key] ?? ""}
            onChange={(e) => setV({ ...v, [f.key]: Number(e.target.value) })}
          />
        ))}
      </div>
    </Modal>
  );
}
