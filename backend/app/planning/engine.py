"""Planning engine: pure functions, no database. Every tab reads the dict `compute()` returns.

Day-granular, hour-accounted, finite-capacity scheduling:
- running orders (in production) are placed first from today and can't move;
- locked orders keep their start date; the rest go in sequence order;
- each route step uses the free machine hours of each working day (Sundays and holidays off),
  never starting before the order's material is in stock or due to arrive;
- a pinned finish date (bar edge dragged) squeezes the work into that window even if it
  overloads the machine: that is the only way a machine gets over capacity.
Money is integer paise. AI never touches any of this.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

EPS = 1e-6
HORIZON_DAYS = 400


# ---- inputs --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Machine:
    id: str
    name: str
    dept: str  # department id
    hours_per_day: float  # normal shifts
    night_hours: float  # extra hours one night shift adds
    cost_ph: int  # machine + power, paise per hour
    night_cost_ph: int  # extra cost per night-shift hour (crew premium etc.)
    operators: int = 1


@dataclass(frozen=True)
class Dept:
    id: str
    name: str
    hours_per_day: float  # labour hours available per day
    cost_ph: int


@dataclass(frozen=True)
class MaterialInfo:
    id: str
    code: str
    name: str
    unit: str
    on_hand: float
    arrival_date: date | None
    arrival_qty: float
    price: int  # paise per unit
    express_cost: int  # paise, flat per express delivery
    express_days: int  # how many days earlier express arrives


@dataclass(frozen=True)
class Step:
    machine: str
    setup: float  # hours
    run: float  # hours for the whole quantity


@dataclass(frozen=True)
class Job:
    id: str
    number: str
    customer: str
    product: str
    qty: float
    unit: str
    value: int  # paise
    deadline: date
    priority: str = "medium"
    tier: str = "standard"
    steps: tuple[Step, ...] = ()
    materials: tuple[tuple[str, float], ...] = ()  # (material id, qty needed)
    running: bool = False
    progress: int = 0  # running orders: % done


@dataclass(frozen=True)
class Factory:
    machines: dict[str, Machine]
    depts: dict[str, Dept]
    materials: dict[str, MaterialInfo]
    closed: frozenset[date] = frozenset()  # factory holidays
    downtime: dict[tuple[str, date], float] = field(default_factory=dict)  # (machine, day) -> hours lost


@dataclass(frozen=True)
class Rules:
    penalty_mode: str = "fixed"  # fixed | percent
    penalty_value: float = 2_000_000  # paise per late day, or % of order value per late day
    overhead_pct: float = 7.0
    packaging_per_unit: int = 0  # paise
    min_margin_pct: float = 18.0


@dataclass
class Inputs:
    start: date
    sequence: list[str]  # job ids, in order
    locks: dict[str, date] = field(default_factory=dict)  # job id -> kept start date
    pins: dict[str, date] = field(default_factory=dict)  # job id -> forced finish date
    fixes: set[str] = field(default_factory=set)


# ---- calendar -------------------------------------------------------------------------------


def is_working(d: date, f: Factory) -> bool:
    return d.weekday() != 6 and d not in f.closed


def next_working(d: date, f: Factory) -> date:
    while not is_working(d, f):
        d += timedelta(1)
    return d


def working_days(a: date, b: date, f: Factory) -> int:
    """Working days d with a < d <= b (negative if b < a)."""
    if b < a:
        return -working_days(b, a, f)
    return sum(1 for i in range(1, (b - a).days + 1) if is_working(a + timedelta(i), f))


def days_in(a: date, b: date, f: Factory) -> list[date]:
    return [a + timedelta(i) for i in range((b - a).days + 1) if is_working(a + timedelta(i), f)]


# ---- scheduling -----------------------------------------------------------------------------


@dataclass
class Placed:
    job: Job
    steps: list[dict[date, float]]  # per step: day -> hours
    material_ready: date
    blocked: str | None = None

    @property
    def start(self) -> date:
        return min(min(s) for s in self.steps if s)

    @property
    def finish(self) -> date:
        return max(max(s) for s in self.steps if s)


@dataclass
class Sched:
    placed: dict[str, Placed]
    used: dict[tuple[str, date], float]
    cap: dict[tuple[str, date], float]  # including night shifts from fixes
    normal_cap: dict[tuple[str, date], float]
    shortages: list[dict[str, Any]]  # material problems
    blocked: dict[str, str]


def _night(fixes: set[str]) -> set[tuple[str, date]]:
    out = set()
    for fx in fixes:
        p = fx.split(":")
        if p[0] == "night" and len(p) == 4:
            a, b = date.fromisoformat(p[2]), date.fromisoformat(p[3])
            out |= {(p[1], a + timedelta(i)) for i in range((b - a).days + 1)}
    return out


def _express(fixes: set[str]) -> set[str]:
    return {fx.split(":")[1] for fx in fixes if fx.startswith("express:")}


def schedule(f: Factory, running: list[Job], jobs: list[Job], inp: Inputs, today: date) -> Sched:
    night = _night(inp.fixes)
    express = _express(inp.fixes)
    used: dict[tuple[str, date], float] = defaultdict(float)
    cap: dict[tuple[str, date], float] = {}
    normal: dict[tuple[str, date], float] = {}

    def capacity(m: str, d: date) -> float:
        if (m, d) not in cap:
            mach = f.machines[m]
            base = max(0.0, mach.hours_per_day - f.downtime.get((m, d), 0.0)) if is_working(d, f) else 0.0
            normal[(m, d)] = base
            cap[(m, d)] = base + (mach.night_hours if (m, d) in night and is_working(d, f) else 0.0)
        return cap[(m, d)]

    def place(step: Step, earliest: date, finish_by: date | None) -> dict[date, float]:
        need = step.setup + step.run
        alloc: dict[date, float] = {}
        if need <= EPS:
            return {next_working(earliest, f): 0.0}
        if finish_by is not None:
            window = days_in(earliest, finish_by, f) or [next_working(finish_by, f)]
            for d in window:
                take = min(max(capacity(step.machine, d) - used[(step.machine, d)], 0.0), need)
                if take > EPS:
                    alloc[d] = take
                    need -= take
            if need > EPS:  # squeeze the rest in: this is a forced overload
                share = need / len(window)
                for d in window:
                    alloc[d] = alloc.get(d, 0.0) + share
        else:
            d = earliest
            for _ in range(HORIZON_DAYS):
                if is_working(d, f):
                    take = min(max(capacity(step.machine, d) - used[(step.machine, d)], 0.0), need)
                    if take > EPS:
                        alloc[d] = take
                        need -= take
                        if need <= EPS:
                            break
                d += timedelta(1)
        for d, h in alloc.items():
            used[(step.machine, d)] += h
            capacity(step.machine, d)
        return alloc

    def run_job(job: Job, earliest: date, ready: date, finish_by: date | None) -> Placed:
        steps = []
        at = max(earliest, ready)
        for st in job.steps:
            alloc = place(st, at, finish_by)
            steps.append(alloc)
            at = max(alloc) if alloc else at
        if not steps:
            steps = [{next_working(at, f): 0.0}]
        return Placed(job, steps, ready)

    placed: dict[str, Placed] = {}
    for j in running:  # remaining work only, from today
        left = 1 - j.progress / 100
        rj = replace(j, steps=tuple(Step(s.machine, 0.0, (s.setup + s.run) * left) for s in j.steps))
        placed[j.id] = run_job(rj, next_working(today, f), today, None)

    # Material: allocate stock in sequence order (locked first, like the placement order).
    order = sorted(jobs, key=lambda j: (j.id not in inp.locks, inp.locks.get(j.id, date.min)))
    pool = {m.id: [m.on_hand, m.arrival_qty] for m in f.materials.values()}
    ready: dict[str, date] = {}
    shortages: list[dict[str, Any]] = []
    for j in order:
        r = inp.start
        for mid, q in j.materials:
            m = f.materials.get(mid)
            if m is None or q <= EPS:
                continue
            have, coming = pool[mid]
            from_stock = min(have, q)
            pool[mid][0] = have - from_stock
            rest = q - from_stock
            if rest <= EPS:
                continue
            from_arrival = min(coming, rest)
            pool[mid][1] = coming - from_arrival
            rest -= from_arrival
            if from_arrival > EPS and m.arrival_date:
                arrives = m.arrival_date - timedelta(m.express_days if mid in express else 0)
                arrives = max(arrives, inp.start)
                if arrives > r:
                    r = arrives
                if arrives > inp.start:
                    shortages.append({"kind": "wait", "material": mid, "qty": from_arrival, "job": j.id,
                                      "until": arrives, "express": mid in express})  # fmt: skip
            if rest > EPS:
                shortages.append({"kind": "short", "material": mid, "qty": rest, "job": j.id,
                                  "express": mid in express})  # fmt: skip
        ready[j.id] = r

    blocked: dict[str, str] = {}
    for j in order:
        lock = inp.locks.get(j.id)
        pin = inp.pins.get(j.id)
        if pin is not None and pin < ready[j.id]:
            blocked[j.id] = (
                f"{j.number} can't finish before its material arrives ({ready[j.id].isoformat()})."
            )
            pin = None
        placed[j.id] = run_job(j, next_working(lock or inp.start, f), ready[j.id], pin)
    for s in shortages:
        p = placed[s["job"]]
        s["needed_by"] = p.start
    return Sched(placed, used, cap, normal, shortages, blocked)


# ---- analysis -------------------------------------------------------------------------------


def _ranges(days: list[date], f: Factory) -> list[tuple[date, date]]:
    """Group days into runs of consecutive working days."""
    out: list[tuple[date, date]] = []
    for d in sorted(days):
        if out and working_days(out[-1][1], d, f) == 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _fmt_day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _fmt_range(a: date, b: date) -> str:
    if a == b:
        return _fmt_day(a)
    if a.month == b.month:
        return f"{a.day}–{b.day} {b.strftime('%b')}"
    return f"{_fmt_day(a)} – {_fmt_day(b)}"


def _qty(q: float, unit: str) -> str:
    return f"{q:,.3f}".rstrip("0").rstrip(".") + f" {unit}"


def analyse(f: Factory, s: Sched, jobs: list[Job], plan_start: date) -> dict[str, Any]:
    """Deliveries, machine/labour load, bottlenecks, parallel runs, overview."""
    plan_ids = [j.id for j in jobs]
    rows: list[dict[str, Any]] = []
    for j in jobs:
        p = s.placed[j.id]
        late = max(0, working_days(j.deadline, p.finish, f)) if p.finish > j.deadline else 0
        buffer = -late if late else working_days(p.finish, j.deadline, f)
        rows.append({"id": j.id, "start": p.start, "finish": p.finish, "late_days": late, "buffer": buffer})
    by_id = {r["id"]: r for r in rows}

    bottlenecks: list[dict[str, Any]] = []
    # machines
    over: dict[str, list[date]] = defaultdict(list)
    for (m, d), h in s.used.items():
        if h > s.cap.get((m, d), 0.0) + EPS:
            over[m].append(d)
    for m, ds in sorted(over.items()):
        for a, b in _ranges(ds, f):
            span = days_in(a, b, f)
            extra = sum(s.used[(m, d)] - s.cap[(m, d)] for d in span)
            who = [j.id for j in jobs if any(_uses(j, s.placed[j.id], m, d) for d in span)]
            name = f.machines[m].name
            bottlenecks.append({"kind": "machine", "resource": name, "machine": m, "from": a, "to": b,
                                "size": round(extra, 1), "orders": who,
                                "title": f"{name} overloaded",
                                "text": f"{_fmt_range(a, b)} · +{extra:.0f} hrs"})  # fmt: skip
    # labour (department hours = machine hours x operators)
    dept_need: dict[tuple[str, date], float] = defaultdict(float)
    dept_extra: dict[tuple[str, date], float] = defaultdict(float)
    for (m, d), h in s.used.items():
        mach = f.machines[m]
        dept_need[(mach.dept, d)] += h * mach.operators
        dept_extra[(mach.dept, d)] += (
            s.cap.get((m, d), 0.0) - s.normal_cap.get((m, d), 0.0)
        ) * mach.operators
    lab_over: dict[str, list[date]] = defaultdict(list)
    for (dp, d), h in dept_need.items():
        if dp in f.depts and h > f.depts[dp].hours_per_day + dept_extra[(dp, d)] + EPS:
            lab_over[dp].append(d)
    for dp, ds in sorted(lab_over.items()):
        for a, b in _ranges(ds, f):
            extra = sum(dept_need[(dp, d)] - f.depts[dp].hours_per_day - dept_extra[(dp, d)]
                        for d in days_in(a, b, f))  # fmt: skip
            name = f.depts[dp].name
            bottlenecks.append({"kind": "labour", "resource": name, "from": a, "to": b, "size": round(extra, 1),
                                "orders": [], "title": f"{name} labour short",
                                "text": f"{_fmt_range(a, b)} · {extra:.0f} hrs over"})  # fmt: skip
    # materials
    for sh in s.shortages:
        if sh["job"] not in by_id:
            continue
        mat = f.materials[sh["material"]]
        j = next(x for x in jobs if x.id == sh["job"])
        if sh["kind"] == "short" and not sh["express"]:
            bottlenecks.append({"kind": "material", "resource": mat.name, "material": mat.id, "from": sh["needed_by"],
                                "to": sh["needed_by"], "size": sh["qty"], "orders": [j.id],
                                "title": f"{mat.name} short {_qty(sh['qty'], mat.unit)}",
                                "text": f"needed {_fmt_day(sh['needed_by'])} for {j.number}"})  # fmt: skip
        elif sh["kind"] == "wait":
            bottlenecks.append({"kind": "material_wait", "resource": mat.name, "material": mat.id,
                                "from": sh["until"], "to": sh["until"], "size": sh["qty"], "orders": [j.id],
                                "title": f"Waiting on {mat.name}",
                                "text": f"arrives {_fmt_day(sh['until'])} · {j.number} can't start before"})  # fmt: skip
    # late deliveries
    for j in jobs:
        r = by_id[j.id]
        if r["late_days"]:
            n = r["late_days"]
            bottlenecks.append({"kind": "late", "resource": j.number, "from": j.deadline, "to": r["finish"],
                                "size": n, "orders": [j.id], "title": f"{j.number} ships {n} day{'s' * (n != 1)} late",
                                "text": f"finishes {_fmt_day(r['finish'])}, due {_fmt_day(j.deadline)}"})  # fmt: skip

    # parallel groups: consecutive (in sequence) orders whose date ranges overlap
    groups: list[list[str]] = []
    for jid in plan_ids:
        r = by_id[jid]
        if groups and any(
            by_id[g]["start"] <= r["finish"] and r["start"] <= by_id[g]["finish"] for g in groups[-1]
        ):
            groups[-1].append(jid)
        else:
            groups.append([jid])
    par = []
    for g in groups:
        machines_shared = set()
        if len(g) > 1:
            for m in f.machines:
                days: dict[date, int] = defaultdict(int)
                for jid in g:
                    for d in {d for st, js in zip(s.placed[jid].steps, _job(jobs, jid).steps, strict=False)
                              if js.machine == m for d in st}:  # fmt: skip
                        days[d] += 1
                if any(v > 1 for v in days.values()):
                    machines_shared.add(f.machines[m].name)
        par.append({"orders": g, "shared": sorted(machines_shared)})

    if jobs:
        start = min([plan_start] + [r["start"] for r in rows])
        end = max(r["finish"] for r in rows)
        plan_machines = {st.machine for j in jobs for st in j.steps}
        span = days_in(start, end, f)
        cap_sum = sum(s.cap.get((m, d), f.machines[m].hours_per_day) for m in plan_machines for d in span)
        use_sum = sum(s.used.get((m, d), 0.0) for m in plan_machines for d in span)
        util = round(100 * use_sum / cap_sum) if cap_sum else 0
        length = len(span)
    else:
        start = end = None
        util = length = 0
    return {"rows": by_id, "bottlenecks": bottlenecks, "groups": par, "start": start, "end": end,
            "days": length, "utilisation": util}  # fmt: skip


def _job(jobs: list[Job], jid: str) -> Job:
    return next(j for j in jobs if j.id == jid)


def _uses(j: Job, p: Placed, m: str, d: date) -> bool:
    return any(st.machine == m and d in alloc for st, alloc in zip(j.steps, p.steps, strict=False))


# ---- money ----------------------------------------------------------------------------------


def job_cost(f: Factory, rules: Rules, j: Job) -> dict[str, int]:
    mat = sum(round(q * f.materials[mid].price) for mid, q in j.materials if mid in f.materials)
    lab = mach = 0
    for st in j.steps:
        m = f.machines[st.machine]
        hrs = st.setup + st.run
        mach += round(hrs * m.cost_ph)
        lab += round(hrs * m.operators * (f.depts[m.dept].cost_ph if m.dept in f.depts else 0))
    over = round((mat + lab + mach) * rules.overhead_pct / 100)
    pack = round(j.qty * rules.packaging_per_unit)
    return {"materials": mat, "labour": lab, "machine": mach, "overheads": over, "packaging": pack,
            "total": mat + lab + mach + over + pack}  # fmt: skip


def penalty(rules: Rules, j: Job, late_days: int) -> int:
    if late_days <= 0:
        return 0
    per_day = rules.penalty_value if rules.penalty_mode == "fixed" else j.value * rules.penalty_value / 100
    return round(per_day * late_days)


def fix_costs(f: Factory, s: Sched, fixes: set[str], jobs: list[Job]) -> dict[str, dict[str, Any]]:
    """Cost of each chosen fix and how it is shared between orders."""
    out: dict[str, dict[str, Any]] = {}
    for fx in sorted(fixes):
        p = fx.split(":")
        share: dict[str, float] = defaultdict(float)
        if p[0] == "night" and len(p) == 4:
            m = f.machines.get(p[1])
            if m is None:
                continue
            hrs, days = 0.0, []
            for (mm, d), h in s.used.items():
                if mm == p[1] and (mm, d) in _night({fx}):
                    extra = max(0.0, h - s.normal_cap.get((mm, d), 0.0))
                    if extra > EPS:
                        hrs += extra
                        days.append(d)
                        for j in jobs:
                            jh = sum(a.get(d, 0.0) for st, a in zip(j.steps, s.placed[j.id].steps, strict=False)
                                     if st.machine == mm)  # fmt: skip
                            if jh > EPS:
                                share[j.id] += jh / h * extra
            cost = round(hrs * m.night_cost_ph)
            rng = _ranges(days, f)
            label = f"Night shift on {m.name}" + (f" · {_fmt_range(rng[0][0], rng[-1][1])}" if rng else "")
            total_share = sum(share.values()) or 1.0
            out[fx] = {"label": label, "cost": cost, "hours": round(hrs, 1),
                       "split": {k: round(cost * v / total_share) for k, v in share.items()}}  # fmt: skip
        elif p[0] == "express":
            mat = f.materials.get(p[1])
            if mat is None:
                continue
            users = {sh["job"] for sh in s.shortages if sh["material"] == p[1]}
            users = users or {j.id for j in jobs if any(mid == p[1] for mid, _ in j.materials)}
            cost = mat.express_cost
            out[fx] = {"label": f"Express {mat.name.lower()}", "cost": cost, "hours": 0,
                       "split": {k: round(cost / len(users)) for k in users} if users else {}}  # fmt: skip
    return out


def finance(
    f: Factory, rules: Rules, jobs: list[Job], a: dict[str, Any], fixes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    tot: dict[str, int] = defaultdict(int)
    for j in jobs:
        c = job_cost(f, rules, j)
        pen = penalty(rules, j, a["rows"][j.id]["late_days"])
        fx = sum(x["split"].get(j.id, 0) for x in fixes.values())
        contrib = j.value - c["total"] - pen - fx
        rows.append({"id": j.id, "value": j.value, "cost": c["total"], "penalty": pen, "fix_cost": fx,
                     "contribution": contrib, "margin": round(100 * contrib / j.value, 1) if j.value else 0.0})  # fmt: skip
        for k, v in c.items():
            tot[k] += v
        tot["value"] += j.value
        tot["penalty"] += pen
        tot["fix_cost"] += fx
    base = tot["value"] - tot["total"]
    contrib = base - tot["penalty"] - tot["fix_cost"]
    days = a["days"] or 1
    return {
        "rows": rows,
        "value": tot["value"],
        "cost": tot["total"] + tot["fix_cost"],
        "mfg_cost": tot["total"],
        "breakdown": {k: tot[k] for k in ("materials", "labour", "machine", "overheads", "packaging")},
        "base_contribution": base,
        "penalty": tot["penalty"],
        "fix_cost": tot["fix_cost"],
        "contribution": contrib,
        "margin": round(100 * contrib / tot["value"], 1) if tot["value"] else 0.0,
        "per_day": round(contrib / days) if jobs else 0,
        "fixes": [{"id": k, **{x: v[x] for x in ("label", "cost")}} for k, v in fixes.items()],
    }


# ---- sequencing rules ------------------------------------------------------------------------

_PRI = {"high": 0, "medium": 1, "low": 2}
_TIER = {"key": 0, "standard": 1, "occasional": 2}


def by_rule(rule: str, jobs: list[Job], f: Factory, rules: Rules, current: list[str]) -> list[str]:
    if rule == "custom":
        known = [i for i in current if any(j.id == i for j in jobs)]
        return known + [j.id for j in sorted(jobs, key=lambda j: (j.deadline, j.number)) if j.id not in known]
    margin = {j.id: (j.value - job_cost(f, rules, j)["total"]) / j.value if j.value else 0 for j in jobs}
    keys = {
        "deadline": lambda j: (j.deadline, _PRI.get(j.priority, 1), j.number),
        "value": lambda j: (-j.value, j.deadline, j.number),
        "margin": lambda j: (-margin[j.id], j.deadline, j.number),
        "priority": lambda j: (_PRI.get(j.priority, 1), _TIER.get(j.tier, 1), j.deadline, j.number),
    }
    return [j.id for j in sorted(jobs, key=keys.get(rule, keys["deadline"]))]


# ---- evaluation, hint, fixes, options --------------------------------------------------------


@dataclass
class Eval:
    sched: Sched
    a: dict[str, Any]
    fin: dict[str, Any]
    fixes: dict[str, dict[str, Any]]

    @property
    def late(self) -> int:
        return sum(1 for r in self.a["rows"].values() if r["late_days"])

    @property
    def problems(self) -> int:
        return len([b for b in self.a["bottlenecks"] if b["kind"] != "late"])

    def key(self) -> tuple[Any, ...]:
        late_days = sum(r["late_days"] for r in self.a["rows"].values())
        return (self.late, late_days, self.problems, self.a["days"], -self.fin["contribution"])


def evaluate(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, today: date) -> Eval:
    ordered = [_job(jobs, i) for i in inp.sequence if any(j.id == i for j in jobs)]
    s = schedule(f, running, ordered, inp, today)
    a = analyse(f, s, ordered, inp.start)
    fx = fix_costs(f, s, inp.fixes, ordered)
    return Eval(s, a, finance(f, rules, ordered, a, fx), fx)


def suggest_hint(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, cur: Eval,
                 today: date) -> dict[str, Any] | None:  # fmt: skip
    """Best single move of one order to another position, if it is strictly better."""
    best: tuple[tuple[Any, ...], list[str], str, str] | None = None
    seq = inp.sequence
    movable = [i for i in seq if i not in inp.locks]
    for i in movable:
        for pos in range(len(seq)):
            new = [x for x in seq if x != i]
            new.insert(pos, i)
            if new == seq:
                continue
            ev = evaluate(f, rules, running, jobs, replace(inp, sequence=new), today)
            if ev.key() < cur.key() and (best is None or ev.key() < best[0]):
                best = (ev.key(), new, i, "")
    if best is None:
        return None
    _, new, _, _ = best
    k = next(i for i, (x, y) in enumerate(zip(seq, new, strict=True)) if x != y)
    moved, before = new[k], seq[k]  # the order that moves earlier, and the one it now precedes
    ev = evaluate(f, rules, running, jobs, replace(inp, sequence=new), today)
    num = {j.id: j.number for j in jobs}
    late = ev.late
    effect = (f"All {len(new)} orders ship on time." if late == 0
              else f"Late deliveries {cur.late} → {late}.")  # fmt: skip
    if ev.a["days"] != cur.a["days"]:
        effect += f" Plan length {cur.a['days']} → {ev.a['days']} days."
    else:
        effect += f" Plan length stays {ev.a['days']} days."
    title = f"Run {num[moved]} before {num[before]}"
    return {"sequence": new, "title": title, "text": effect, "moved": moved}


def suggest_fixes(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, cur: Eval,
                  today: date) -> list[dict[str, Any]]:  # fmt: skip
    """Night shifts for late orders / overloaded machines, express delivery for short material."""
    base = replace(inp, fixes=set())
    base_eval = evaluate(f, rules, running, jobs, base, today)
    cands: set[str] = set()
    for b in base_eval.a["bottlenecks"]:
        if b["kind"] in ("material", "material_wait"):
            cands.add(f"express:{b['material']}")
        elif b["kind"] == "machine":
            cands.add(f"night:{b['machine']}:{b['from'].isoformat()}:{b['to'].isoformat()}")
        elif b["kind"] == "late":
            j = _job(jobs, b["orders"][0])
            p = base_eval.sched.placed[j.id]
            for st, alloc in zip(j.steps, p.steps, strict=False):
                if alloc:
                    cands.add(f"night:{st.machine}:{min(alloc).isoformat()}:{j.deadline.isoformat()}")
    out = []
    for fx in sorted(cands):
        ev = evaluate(f, rules, running, jobs, replace(base, fixes={fx}), today)
        if ev.key() >= base_eval.key():
            continue
        info = ev.fixes.get(fx, {"label": fx, "cost": 0})
        avoided = base_eval.fin["penalty"] - ev.fin["penalty"]
        fixed = [b["title"] for b in base_eval.a["bottlenecks"]
                 if b["title"] not in {x["title"] for x in ev.a["bottlenecks"]}]  # fmt: skip
        out.append({"id": fx, "label": info["label"], "cost": info["cost"], "penalty_avoided": avoided,
                    "solves": fixed, "selected": fx in inp.fixes})  # fmt: skip
    # one night-shift suggestion per machine: keep the cheapest that solves the most
    best: dict[str, dict[str, Any]] = {}
    for x in out:
        k = x["id"].rsplit(":", 2)[0] if x["id"].startswith("night:") else x["id"]
        if k not in best or (-len(x["solves"]), x["cost"]) < (-len(best[k]["solves"]), best[k]["cost"]):
            best[k] = x
    keep = list(best.values())
    for fx in inp.fixes:  # chosen fixes always stay listed
        if fx not in {x["id"] for x in keep}:
            info = cur.fixes.get(fx, {"label": fx, "cost": 0})
            keep.append({"id": fx, "label": info["label"], "cost": info["cost"], "penalty_avoided": 0,
                         "solves": [], "selected": True})  # fmt: skip
    return sorted(keep, key=lambda x: x["label"])


def _option_metrics(f: Factory, ev: Eval, running: list[Job], ids: list[str], today: date) -> dict[str, Any]:
    run_end = max((ev.sched.placed[j.id].finish for j in running), default=None)
    alongside = 0
    idle: list[tuple[str, date]] = []
    if run_end and ev.a["start"]:
        alongside = sum(1 for i in ids if ev.a["rows"][i]["start"] <= run_end)
        for d in days_in(max(ev.a["start"], next_working(today, f)), run_end, f):
            for m in f.machines.values():
                if ev.sched.used.get((m.id, d), 0.0) <= EPS and m.hours_per_day > 0:
                    idle.append((m.name, d))
    return {"orders": ids, "value": ev.fin["value"], "start": ev.a["start"], "end": ev.a["end"],
            "days": ev.a["days"], "alongside": alongside, "idle_days": len(idle),
            "idle_machines": sorted({n for n, _ in idle}), "utilisation": ev.a["utilisation"],
            "bottlenecks": ev.problems, "bottleneck_names": [b["resource"] for b in ev.a["bottlenecks"]
                                                              if b["kind"] != "late"],
            "late": [i for i in ids if ev.a["rows"][i]["late_days"]],
            "contribution": ev.fin["contribution"], "margin": ev.fin["margin"], "per_day": ev.fin["per_day"],
            "rows": {i: {"start": ev.a["rows"][i]["start"], "finish": ev.a["rows"][i]["finish"],
                         "late_days": ev.a["rows"][i]["late_days"]} for i in ids}}  # fmt: skip


def options(f: Factory, rules: Rules, running: list[Job], cands: list[Job], selected: list[str], inp: Inputs,
            today: date) -> dict[str, Any]:  # fmt: skip
    """Your selection, partly optimized (keeps yours, may add), fully optimized (free choice)."""
    by = {j.id: j for j in cands}

    def ev_of(ids: list[str]) -> Eval:
        js = [by[i] for i in ids]
        seq = by_rule("deadline", js, f, rules, [])
        return evaluate(f, rules, running, js, Inputs(inp.start, seq), today)

    def score(ev: Eval) -> tuple[Any, ...]:
        # No late deliveries first; then contribution per production day over the SAME window for every
        # option (so dropping work never looks better), then fewer bottlenecks, then a shorter plan.
        return (ev.late, -ev.fin["contribution"], ev.problems, ev.a["days"])

    def search(start: list[str], may_drop: bool) -> list[str]:
        cur = list(start)
        cur_ev = ev_of(cur) if cur else None
        for _ in range(40):
            moves = [[*cur, c] for c in by if c not in cur]
            if may_drop:
                moves += [[x for x in cur if x != c] for c in cur if len(cur) > 1]
            best, best_ev = None, cur_ev
            for mv in moves:
                e = ev_of(mv)
                if best_ev is None or score(e) < score(best_ev):
                    best, best_ev = mv, e
            if best is None:
                break
            cur, cur_ev = best, best_ev
        return cur

    out = {}
    own = [i for i in selected if i in by]
    for key, ids in (("own", own), ("part", search(own, False)), ("full", search(own, True))):
        ids = sorted(ids, key=lambda i: own.index(i) if i in own else len(own))
        out[key] = _option_metrics(f, ev_of(ids), running, ids, today) if ids else None
    return out


# ---- the one result every tab reads ---------------------------------------------------------


def _iso(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {(k.isoformat() if isinstance(k, date) else k): _iso(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_iso(x) for x in v]
    return v


def compute(f: Factory, rules: Rules, running: list[Job], cands: list[Job], selected: list[str], rule: str,
            inp: Inputs, today: date, requested: set[str], opts: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """Everything the 5 tabs show, from one set of inputs. `opts` reuses unchanged selection options."""
    by = {j.id: j for j in cands}
    jobs = [by[i] for i in selected if i in by]
    inp.sequence = by_rule(rule, jobs, f, rules, inp.sequence)
    inp.locks = {k: v for k, v in inp.locks.items() if k in inp.sequence}
    inp.pins = {k: v for k, v in inp.pins.items() if k in inp.sequence}
    cur = evaluate(f, rules, running, jobs, inp, today)
    before = evaluate(f, rules, running, jobs, replace(inp, fixes=set()), today) if inp.fixes else cur
    a = cur.a
    num = {j.id: j.number for j in cands}

    # Tab 1 --------------------------------------------------------------------------------
    orders = {}
    for j in cands:
        c = job_cost(f, rules, j)["total"]
        orders[j.id] = {"number": j.number, "customer": j.customer, "product": j.product, "qty": j.qty,
                        "unit": j.unit, "value": j.value, "deadline": j.deadline, "priority": j.priority,
                        "est_margin": round(100 * (j.value - c) / j.value, 1) if j.value else 0.0}  # fmt: skip
    running_rows = [{"id": j.id, "number": j.number, "customer": j.customer, "product": j.product,
                     "progress": j.progress, "start": cur.sched.placed[j.id].start,
                     "finish": cur.sched.placed[j.id].finish,
                     "machines": [f.machines[s.machine].name for s in j.steps]} for j in running]  # fmt: skip
    if opts is None:
        opts = _iso(options(f, rules, running, cands, selected, inp, today))

    # Tab 2 --------------------------------------------------------------------------------
    over_machines = {b["resource"] for b in a["bottlenecks"] if b["kind"] == "machine"}
    group_of = {jid: gi for gi, g in enumerate(a["groups"]) for jid in g["orders"]}
    seq = []
    for rank, jid in enumerate(inp.sequence, start=1):
        j, r = by[jid], a["rows"][jid]
        names = [f.machines[s.machine].name for s in j.steps]
        short = any(
            b["kind"] in ("material", "material_wait") and jid in b["orders"] for b in a["bottlenecks"]
        )
        status = "late" if r["late_days"] else ("material" if short else "on_time")
        seq.append({"id": jid, "rank": rank, "start": r["start"], "finish": r["finish"], "deadline": j.deadline,
                    "buffer": r["buffer"], "late_days": r["late_days"], "group": group_of[jid],
                    "machines": names, "warn_machines": [n for n in names if n in over_machines],
                    "locked": jid in inp.locks, "pinned": inp.pins.get(jid), "status": status})  # fmt: skip
    problems = [b for b in a["bottlenecks"]]
    on_time = sum(1 for r in a["rows"].values() if not r["late_days"])
    hint = suggest_hint(f, rules, running, jobs, inp, cur, today) if jobs else None
    fixes = suggest_fixes(f, rules, running, jobs, inp, cur, today) if jobs else []

    # Tab 3 --------------------------------------------------------------------------------
    first = min([today] + [p.start for p in cur.sched.placed.values()])
    last = max(
        [first + timedelta(13)] + [p.finish for p in cur.sched.placed.values()] + [j.deadline for j in jobs]
    )
    days = [first + timedelta(i) for i in range((last - first).days + 2)]
    gantt = []
    for j in running + [by[i] for i in inp.sequence]:
        p = cur.sched.placed[j.id]
        steps: list[dict[str, Any]] = []
        for st, alloc in zip(j.steps, p.steps, strict=False):
            if not alloc:
                continue
            steps.append({"machine": st.machine, "name": f.machines[st.machine].name, "start": min(alloc),
                          "finish": max(alloc), "hours": {d: round(h, 2) for d, h in sorted(alloc.items())},
                          "setup": st.setup})  # fmt: skip
        over_days = sorted({d for st in steps for d in st["hours"]
                            if cur.sched.used[(st["machine"], d)] > cur.sched.cap[(st["machine"], d)] + EPS})  # fmt: skip
        gantt.append({"id": j.id, "running": j.running, "steps": steps, "start": p.start, "finish": p.finish,
                      "deadline": None if j.running else j.deadline, "over_days": over_days,
                      "short": any(b["kind"] == "material" and j.id in b["orders"] for b in a["bottlenecks"])})  # fmt: skip
    load = []
    for m in f.machines.values():
        per: dict[date, int | None] = {}
        for d in days:
            cv = cur.sched.cap.get((m.id, d))
            u = cur.sched.used.get((m.id, d), 0.0)
            if cv is None:
                cv = max(0.0, m.hours_per_day - f.downtime.get((m.id, d), 0.0)) if is_working(d, f) else 0.0
            per[d] = None if cv <= EPS and u <= EPS else (round(100 * u / cv) if cv > EPS else 999)
        load.append({"machine": m.id, "name": m.name, "days": per,
                     "over": any(v is not None and v > 100 for v in per.values())})  # fmt: skip

    # Purchase needs + Tab 5 -----------------------------------------------------------------
    needs: dict[str, dict[str, Any]] = {}
    for sh in cur.sched.shortages:
        if sh["job"] not in a["rows"]:
            continue
        mat = f.materials[sh["material"]]
        n = needs.setdefault(mat.id, {"material": mat.id, "code": mat.code, "name": mat.name, "unit": mat.unit, "qty": 0.0,
                                    "needed_by": sh["needed_by"], "orders": [], "express": sh["express"],
                                    "kind": sh["kind"], "requested": mat.id in requested})  # fmt: skip
        n["qty"] = round(n["qty"] + sh["qty"], 3)
        n["needed_by"] = min(n["needed_by"], sh["needed_by"])
        n["orders"].append(num[sh["job"]])
    fin_with, fin_before = cur.fin, before.fin
    min_buf = min(seq, key=lambda x: x["buffer"]) if seq else None
    machine_b = [b for b in a["bottlenecks"] if b["kind"] == "machine"]
    labour_b = [b for b in a["bottlenecks"] if b["kind"] == "labour"]
    open_po = [n for n in needs.values() if not n["requested"]]
    checks: list[dict[str, Any]] = [
        {"ok": not cur.late, "title": f"All {len(jobs)} orders ship on time" if not cur.late
         else f"{cur.late} order{'s ship' if cur.late != 1 else ' ships'} late",
         "text": f"Smallest buffer: {num[min_buf['id']]}, {max(min_buf['buffer'], 0)} days" if min_buf else ""},
        {"ok": not machine_b, "title": "Machine capacity within limits" if not machine_b
         else "Machines over capacity", "text": "; ".join(f"{b['resource']} {b['text']}" for b in machine_b)},
        {"ok": not open_po, "title": "Material POs raised" if not open_po
         else f"{len(open_po)} material PO{'s' * (len(open_po) != 1)} not raised yet",
         "text": "; ".join(f"{_qty(n['qty'], n['unit'])} {n['name']} by {_fmt_day(n['needed_by'])}" for n in open_po),
         "action": "raise_po" if open_po else None},
        {"ok": not labour_b, "title": "Labour and shifts covered" if not labour_b else "Labour short",
         "text": "; ".join(f"{b['resource']} {b['text']}" for b in labour_b)},
        {"ok": fin_with["margin"] >= rules.min_margin_pct,
         "title": f"Margin {'above' if fin_with['margin'] >= rules.min_margin_pct else 'below'} your "
                  f"{rules.min_margin_pct:g}% minimum", "text": f"{fin_with['margin']}% after fixes",
         "setting": "min_margin_pct"},
    ]  # fmt: skip

    lines = [f"{b['title']} · {b['text']}" for b in problems]
    out: dict[str, Any] = _iso({
        "selection": {"orders": orders, "selected": [i for i in selected if i in by], "running": running_rows,
                      "options": opts},
        "sequence": {"rule": rule, "start": inp.start, "rows": seq, "groups": a["groups"], "hint": hint,
                     "overview": {"orders": len(jobs), "start": a["start"], "end": a["end"], "days": a["days"],
                                  "utilisation": a["utilisation"], "on_time": on_time,
                                  "bottlenecks": len([b for b in problems if b["kind"] != "late"]),
                                  "parallel": sum(1 for g in a["groups"] if len(g["orders"]) > 1)},
                     "feasibility": {"ok": not problems, "lines": lines}},
        "schedule": {"days": days, "today": today, "rows": gantt, "load": load,
                     "bottlenecks": [b for b in problems if b["kind"] != "late"]},
        "finance": {"before": fin_before, "with": fin_with, "fixes": fixes},
        "approval": {"checks": checks, "ready": sum(1 for ck in checks if ck["ok"]), "total": len(checks)},
        "purchase_needs": list(needs.values()),
        "blocked": cur.sched.blocked,
        "inputs": {"sequence": inp.sequence, "locks": inp.locks, "pins": inp.pins, "fixes": sorted(inp.fixes)},
    })  # fmt: skip
    return out


TAB_SECTIONS = {
    1: ("selection",),
    2: ("sequence",),
    3: ("schedule",),
    4: ("finance",),
    5: ("approval", "purchase_needs"),
}


def changed_tabs(old: dict[str, Any] | None, new: dict[str, Any]) -> list[int]:
    if not old:
        return []
    return [t for t, keys in TAB_SECTIONS.items() if any(old.get(k) != new.get(k) for k in keys)]


def bottleneck_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """For the reorder warning: what gets worse, what gets better, delivery changes."""

    def idx(r: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {f"{b['kind']}:{b['resource']}": b for b in r["schedule"]["bottlenecks"]}

    o, n = idx(old), idx(new)
    worse = [
        b | {"was": o[k]["text"] if k in o else None}
        for k, b in n.items()
        if k not in o or b["size"] > o[k]["size"] + EPS
    ]
    better = [b for k, b in o.items() if k not in n or n[k]["size"] < b["size"] - EPS]
    od = {r["id"]: r for r in old["sequence"]["rows"]}
    deliveries = []
    for r in new["sequence"]["rows"]:
        p = od.get(r["id"])
        if p and p["late_days"] != r["late_days"]:
            deliveries.append(
                {"id": r["id"], "was": p["late_days"], "now": r["late_days"], "finish": r["finish"]}
            )
    late_worse = any(d["now"] > d["was"] for d in deliveries)
    return {"worse": worse, "better": better, "deliveries": deliveries, "warn": bool(worse) or late_worse}
