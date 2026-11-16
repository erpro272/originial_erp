import { useState, type ReactNode } from "react";
import { Panel } from "@/components/kit/Kit";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { cn } from "@/lib/cn";
import { FactoryLayout } from "./FactoryLayout";
import { STATUS } from "./status";

/** The Factory Layout card (Production tab and Executive Dashboard): Layout / Status view, legend, hover card. */
export function FactoryPanel({ id = "factory-h", note }: { id?: string; note?: ReactNode }) {
  const [view, setView] = useState<"layout" | "status">("layout");
  return (
    <Panel
      id={id}
      title="Factory Layout"
      icon="map"
      bodyClassName="p-0"
      aside={
        <SegmentedControl
          label="Layout or status view"
          value={view}
          onChange={(v) => setView(v)}
          options={[
            { value: "layout" as const, label: "Layout View" },
            { value: "status" as const, label: "Status View" },
          ]}
        />
      }
    >
      {note}
      <div className="flex gap-6 overflow-x-auto p-6">
        <div className="flex-1">
          <FactoryLayout view={view} />
        </div>
        <ul className="m-0 flex h-fit shrink-0 list-none flex-col gap-3 rounded-card border border-line p-4 text-[13px] text-ink-2 shadow-sm">
          {(["running", "idle", "maintenance", "issue"] as const).map((s) => (
            <li key={s} className="flex items-center gap-3">
              <span className={cn("size-3 rounded-full", STATUS[s].dot)} />
              {STATUS[s].label}
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
