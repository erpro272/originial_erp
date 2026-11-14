import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useFactory, usePutFactory, type Factory } from "./api";

const cell =
  "w-full min-w-0 rounded-lg border border-line-input bg-white px-2.5 py-1.5 text-sm disabled:bg-surface";
const rs = (paise: number) => String(paise / 100);
const toPaise = (s: string) => Math.round(Number(s || 0) * 100);

/** Machines, routes, labour and costs the planner uses. Every planning number starts here. */
export function FactorySetupPage() {
  const { can } = useAuth();
  const edit = can("settings.write");
  const q = useFactory();
  const put = usePutFactory();
  const { toast } = useToast();
  const [draft, setDraft] = useState<Factory | null>(null); // the owner's unsaved edits
  const f = draft ?? q.data;
  if (!f) return <LoadingState label="Loading factory set-up" />;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(q.data);
  const set = (fn: (d: Factory) => void) => {
    const n = structuredClone(f);
    fn(n);
    setDraft(n);
  };
  const save = async () => {
    try {
      await put.mutateAsync(f);
      setDraft(null);
      toast({ title: "Factory set-up saved · the plan recalculates", tone: "success" });
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't save.", tone: "error" });
    }
  };
  const machineNames = f.machines.map((m) => m.name);

  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        title="Factory setup"
        subtitle="Machines, how each product is made, labour and costs. Planning uses these for every schedule and number."
        aside={
          <div className="flex gap-2">
            <Button asChild variant="pill">
              <Link to="/planning">← Back to plan</Link>
            </Button>
            {edit && (
              <Button onClick={save} disabled={!dirty || put.isPending}>
                Save changes
              </Button>
            )}
          </div>
        }
      />
      {!edit && (
        <p className="m-0 text-sm text-muted">Only the owner can change the factory set-up.</p>
      )}

      <Block
        title="Departments"
        hint="Labour pools. Machines draw their operators from a department."
      >
        <Table head={["Name", "Labour hours / day", "₹ per hour", ""]}>
          {f.departments.map((d, i) => (
            <tr key={i}>
              <Td>
                <input
                  aria-label="Department name"
                  className={cell}
                  disabled={!edit}
                  value={d.name}
                  onChange={(e) => set((x) => void (x.departments[i]!.name = e.target.value))}
                />
              </Td>
              <Td>
                <input
                  aria-label="Labour hours per day"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={d.hours_per_day}
                  onChange={(e) =>
                    set((x) => void (x.departments[i]!.hours_per_day = e.target.value))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Rupees per hour"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={rs(d.cost_per_hour_paise)}
                  onChange={(e) =>
                    set(
                      (x) => void (x.departments[i]!.cost_per_hour_paise = toPaise(e.target.value)),
                    )
                  }
                />
              </Td>
              <Td>
                <Remove show={edit} onClick={() => set((x) => void x.departments.splice(i, 1))} />
              </Td>
            </tr>
          ))}
        </Table>
        {edit && (
          <Add
            onClick={() =>
              set(
                (x) =>
                  void x.departments.push({ name: "", hours_per_day: "8", cost_per_hour_paise: 0 }),
              )
            }
          >
            + Add department
          </Add>
        )}
      </Block>

      <Block
        title="Machines"
        hint="Capacity per day = hours per shift × shifts. A night shift adds one more shift at the night rate."
      >
        <Table
          head={[
            "Name",
            "Department",
            "Hours / shift",
            "Shifts / day",
            "Operators",
            "₹ / hour (machine + power)",
            "Night shift ₹ / hour extra",
            "",
          ]}
        >
          {f.machines.map((m, i) => (
            <tr key={i}>
              <Td>
                <input
                  aria-label="Machine name"
                  className={cell}
                  disabled={!edit}
                  value={m.name}
                  onChange={(e) => set((x) => void (x.machines[i]!.name = e.target.value))}
                />
              </Td>
              <Td>
                <select
                  aria-label="Department"
                  className={cell}
                  disabled={!edit}
                  value={m.department}
                  onChange={(e) => set((x) => void (x.machines[i]!.department = e.target.value))}
                >
                  {f.departments.map((d) => (
                    <option key={d.name}>{d.name}</option>
                  ))}
                </select>
              </Td>
              <Td>
                <input
                  aria-label="Hours per shift"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={m.hours_per_shift}
                  onChange={(e) =>
                    set((x) => void (x.machines[i]!.hours_per_shift = e.target.value))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Shifts per day"
                  className={cell}
                  disabled={!edit}
                  inputMode="numeric"
                  value={m.shifts_per_day}
                  onChange={(e) =>
                    set((x) => void (x.machines[i]!.shifts_per_day = Number(e.target.value) || 0))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Operators"
                  className={cell}
                  disabled={!edit}
                  inputMode="numeric"
                  value={m.operators}
                  onChange={(e) =>
                    set((x) => void (x.machines[i]!.operators = Number(e.target.value) || 0))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Rupees per hour"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={rs(m.cost_per_hour_paise)}
                  onChange={(e) =>
                    set((x) => void (x.machines[i]!.cost_per_hour_paise = toPaise(e.target.value)))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Night shift rupees per hour"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={rs(m.night_shift_cost_per_hour_paise)}
                  onChange={(e) =>
                    set(
                      (x) =>
                        void (x.machines[i]!.night_shift_cost_per_hour_paise = toPaise(
                          e.target.value,
                        )),
                    )
                  }
                />
              </Td>
              <Td>
                <Remove show={edit} onClick={() => set((x) => void x.machines.splice(i, 1))} />
              </Td>
            </tr>
          ))}
        </Table>
        {edit && (
          <Add
            onClick={() =>
              set(
                (x) =>
                  void x.machines.push({
                    name: "",
                    department: x.departments[0]?.name ?? "",
                    hours_per_shift: "8",
                    shifts_per_day: 1,
                    operators: 1,
                    cost_per_hour_paise: 0,
                    night_shift_cost_per_hour_paise: 0,
                  }),
              )
            }
          >
            + Add machine
          </Add>
        )}
      </Block>

      <Block
        title="How each product is made"
        hint="Machine steps in order. Time per order = setup + minutes per piece × quantity."
      >
        <div className="flex flex-col divide-y divide-divider">
          {f.routes.map((r, ri) => (
            <div key={r.product_id} className="flex flex-col gap-2 py-3.5">
              <b className="text-sm">{r.product}</b>
              {r.steps.length === 0 && (
                <span className="text-[13px] text-md">
                  No steps yet: this product can't be scheduled.
                </span>
              )}
              {r.steps.map((s, si) => (
                <div
                  key={si}
                  className="grid grid-cols-[24px_minmax(140px,1fr)_120px_140px_32px] items-center gap-2 text-sm"
                >
                  <span className="text-muted">{si + 1}.</span>
                  <select
                    aria-label="Machine"
                    className={cell}
                    disabled={!edit}
                    value={s.machine}
                    onChange={(e) =>
                      set((x) => void (x.routes[ri]!.steps[si]!.machine = e.target.value))
                    }
                  >
                    {machineNames.map((n) => (
                      <option key={n}>{n}</option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1.5 text-[13px] text-muted">
                    <input
                      aria-label="Setup hours"
                      className={cell}
                      disabled={!edit}
                      inputMode="decimal"
                      value={s.setup_hours}
                      onChange={(e) =>
                        set((x) => void (x.routes[ri]!.steps[si]!.setup_hours = e.target.value))
                      }
                    />
                    h setup
                  </label>
                  <label className="flex items-center gap-1.5 text-[13px] text-muted">
                    <input
                      aria-label="Minutes per piece"
                      className={cell}
                      disabled={!edit}
                      inputMode="decimal"
                      value={s.minutes_per_unit}
                      onChange={(e) =>
                        set(
                          (x) => void (x.routes[ri]!.steps[si]!.minutes_per_unit = e.target.value),
                        )
                      }
                    />
                    min/pc
                  </label>
                  <Remove
                    show={edit}
                    onClick={() => set((x) => void x.routes[ri]!.steps.splice(si, 1))}
                  />
                </div>
              ))}
              {edit && machineNames.length > 0 && (
                <Add
                  onClick={() =>
                    set(
                      (x) =>
                        void x.routes[ri]!.steps.push({
                          machine: machineNames[0]!,
                          setup_hours: "0",
                          minutes_per_unit: "0",
                        }),
                    )
                  }
                >
                  + Add step
                </Add>
              )}
            </div>
          ))}
        </div>
      </Block>

      <Block
        title="Material costs"
        hint="Price per unit, and what an express delivery costs and how many days earlier it arrives."
      >
        <Table
          head={[
            "Material",
            "₹ per unit",
            "Express ₹",
            "Express arrives (days earlier)",
            "Express supplier",
          ]}
        >
          {f.materials.map((m, i) => (
            <tr key={m.id}>
              <Td>
                <span className="text-sm">
                  {m.name}{" "}
                  <span className="font-mono text-xs text-muted">
                    {m.code} · per {m.unit}
                  </span>
                </span>
              </Td>
              <Td>
                <input
                  aria-label="Rupees per unit"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={rs(m.price_per_unit_paise)}
                  onChange={(e) =>
                    set(
                      (x) => void (x.materials[i]!.price_per_unit_paise = toPaise(e.target.value)),
                    )
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Express rupees"
                  className={cell}
                  disabled={!edit}
                  inputMode="decimal"
                  value={rs(m.express_cost_paise)}
                  onChange={(e) =>
                    set((x) => void (x.materials[i]!.express_cost_paise = toPaise(e.target.value)))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Express days earlier"
                  className={cell}
                  disabled={!edit}
                  inputMode="numeric"
                  value={m.express_days}
                  onChange={(e) =>
                    set((x) => void (x.materials[i]!.express_days = Number(e.target.value) || 0))
                  }
                />
              </Td>
              <Td>
                <input
                  aria-label="Express supplier"
                  className={cell}
                  disabled={!edit}
                  value={m.express_supplier ?? ""}
                  onChange={(e) =>
                    set((x) => void (x.materials[i]!.express_supplier = e.target.value || null))
                  }
                />
              </Td>
            </tr>
          ))}
        </Table>
      </Block>

      <Block
        title="Days off and maintenance"
        hint="A whole-factory day off (holiday), or hours a machine is down."
      >
        <Table head={["Day", "Machine", "Hours lost", "Reason", ""]}>
          {f.downtime.map((d, i) => (
            <tr key={i}>
              <Td>
                <input
                  type="date"
                  aria-label="Day"
                  className={cell}
                  disabled={!edit}
                  value={d.day}
                  onChange={(e) => set((x) => void (x.downtime[i]!.day = e.target.value))}
                />
              </Td>
              <Td>
                <select
                  aria-label="Machine"
                  className={cell}
                  disabled={!edit}
                  value={d.machine ?? ""}
                  onChange={(e) =>
                    set((x) => void (x.downtime[i]!.machine = e.target.value || null))
                  }
                >
                  <option value="">Whole factory (holiday)</option>
                  {machineNames.map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </Td>
              <Td>
                <input
                  aria-label="Hours lost"
                  className={cell}
                  disabled={!edit || !d.machine}
                  placeholder="All day"
                  inputMode="decimal"
                  value={d.hours ?? ""}
                  onChange={(e) => set((x) => void (x.downtime[i]!.hours = e.target.value || null))}
                />
              </Td>
              <Td>
                <input
                  aria-label="Reason"
                  className={cell}
                  disabled={!edit}
                  value={d.reason ?? ""}
                  onChange={(e) =>
                    set((x) => void (x.downtime[i]!.reason = e.target.value || null))
                  }
                />
              </Td>
              <Td>
                <Remove show={edit} onClick={() => set((x) => void x.downtime.splice(i, 1))} />
              </Td>
            </tr>
          ))}
        </Table>
        {edit && (
          <Add
            onClick={() =>
              set(
                (x) =>
                  void x.downtime.push({
                    day: new Date().toISOString().slice(0, 10),
                    machine: null,
                    hours: null,
                    reason: "",
                  }),
              )
            }
          >
            + Add day
          </Add>
        )}
      </Block>
    </div>
  );
}

function Block({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-line p-5">
      <div>
        <h2 className="m-0 text-[17px] font-semibold">{title}</h2>
        <p className="m-0 mt-1 text-[13px] text-muted">{hint}</p>
      </div>
      {children}
    </section>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
            {head.map((h, i) => (
              <th key={i} className="px-2 py-2 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

const Td = ({ children }: { children: ReactNode }) => (
  <td className="border-t border-divider px-2 py-1.5">{children}</td>
);

function Remove({ show, onClick }: { show: boolean; onClick: () => void }) {
  return show ? (
    <button
      type="button"
      aria-label="Remove"
      onClick={onClick}
      className="cursor-pointer rounded-lg border-0 bg-transparent px-2 py-1 text-lg leading-none text-subtle hover:bg-hi-bg hover:text-hi"
    >
      ×
    </button>
  ) : null;
}

function Add({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="cursor-pointer self-start border-0 bg-transparent p-0 text-[13px] text-link"
    >
      {children}
    </button>
  );
}
