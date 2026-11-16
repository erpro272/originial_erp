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
# Bump when the engine's logic changes, so saved plan results are recalculated (part of the fingerprint).
ENGINE_VERSION = 13
FULL_POOL = 10  # orders the fully optimized option searches exhaustively (2^N subsets)
FULL_REFINE = 8  # best subsets whose sequence is then improved by pairwise swaps
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
    inspection: bool = False  # QC stations: not counted as idle production capacity


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
    express_days: int  # express delivery time (days after ordering); also how much an incoming delivery
    # can be brought forward
    supplier: str = ""  # express supplier


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
    # "Best score" rule, as an ordered list of criteria (company setting `planning-objective`).
    # Default = the mockup rule: no late deliveries where possible, then the most contribution per
    # production day, then prefer filling machines left idle by running orders, then fewer bottlenecks.
    criteria: tuple[str, ...] = ("late", "per_day", "idle", "bottlenecks")


@dataclass
class Inputs:
    start: date
    sequence: list[str]  # job ids, in order
    locks: dict[str, date] = field(default_factory=dict)  # job id -> kept start date
    pins: dict[str, date] = field(default_factory=dict)  # job id -> forced finish date
    fixes: set[str] = field(default_factory=set)
    # material id -> the day a PO for it was actually requested (purchasing records, not a plan choice)
    ordered: dict[str, date] = field(default_factory=dict)
    # night-shift intent -> the days it was worked out to need (see resolve_night)
    night_windows: dict[str, tuple[date, date]] = field(default_factory=dict)


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
    # hours an order forced to finish by a date (pin) could not fit in its machines' working time
    overflow: dict[str, float] = field(default_factory=dict)
    # time of day (hours) each machine finishes on each day: a step that waits for the previous route
    # step ends later than its hours alone say (that later end is what a night shift pays for)
    clock: dict[tuple[str, date], float] = field(default_factory=dict)
    # night-shift fix id -> the (machine, day) pairs it opens
    night_days: dict[str, set[tuple[str, date]]] = field(default_factory=dict)


def night_target(fx: str) -> str | None:
    """`night:<machine>:for:<order id>` -> the order the night shift is for (None for other fixes)."""
    p = fx.split(":")
    return p[3] if p[0] == "night" and len(p) == 4 and p[2] == "for" else None


def _night_days(fx: str, f: Factory, jobs: list[Job], start: date,
                windows: dict[str, tuple[date, date]] | None = None) -> set[tuple[str, date]]:  # fmt: skip
    """The machine-days a night-shift fix opens.

    `night:<machine>:for:<order>` is an intent: worked out again on every recalculation, from the plan start
    to that order's deadline, so it follows the order when other changes (another fix, a reorder) move it.
    `night:<machine>:<from>:<to>` is the older fixed window (kept for plans saved before)."""
    p = fx.split(":")
    if p[0] != "night" or len(p) != 4 or p[1] not in f.machines:
        return set()
    if p[2] == "for":
        j = next((x for x in jobs if x.id == p[3]), None)
        if j is None:
            return set()
        a, b = (windows or {}).get(fx, (start, max(start, j.deadline)))
        return {(p[1], d) for d in days_in(a, b, f)}
    a, b = date.fromisoformat(p[2]), date.fromisoformat(p[3])
    return {(p[1], a + timedelta(i)) for i in range((b - a).days + 1)}


def _express(fixes: set[str]) -> set[str]:
    return {fx.split(":")[1] for fx in fixes if fx.startswith("express:")}


def schedule(f: Factory, running: list[Job], jobs: list[Job], inp: Inputs, today: date) -> Sched:
    # night-shift hours per (machine, day) and who may use them: the target order, or anyone (older windows)
    night_days = {
        fx: _night_days(fx, f, jobs, inp.start, inp.night_windows)
        for fx in sorted(inp.fixes)
        if fx.startswith("night:")
    }
    night: dict[tuple[str, date], set[str | None]] = defaultdict(set)
    for fx, days in night_days.items():
        for md in days:
            night[md].add(night_target(fx))
    express = _express(inp.fixes)
    used: dict[tuple[str, date], float] = defaultdict(float)
    cap: dict[tuple[str, date], float] = {}
    normal: dict[tuple[str, date], float] = {}
    overflow: dict[str, float] = defaultdict(float)
    clock: dict[tuple[str, date], float] = defaultdict(float)  # time of day each machine finishes its work
    current: list[str] = [""]  # the job being placed

    def capacity(m: str, d: date) -> float:
        if (m, d) not in cap:
            mach = f.machines[m]
            base = max(0.0, mach.hours_per_day - f.downtime.get((m, d), 0.0)) if is_working(d, f) else 0.0
            normal[(m, d)] = base
            cap[(m, d)] = base + (mach.night_hours if (m, d) in night and is_working(d, f) else 0.0)
        return cap[(m, d)]

    def avail(m: str, d: date) -> float:
        """Hours the order being placed may use: night hours only if the shift is for this order (or anyone)."""
        total = capacity(m, d)
        owners = night.get((m, d))
        if owners and None not in owners and current[0] not in owners:
            return normal[(m, d)]  # the night shift on this day is booked for another order
        return total

    def place(
        step: Step, earliest: date, finish_by: date | None, after: float = 0.0
    ) -> tuple[dict[date, float], float]:
        """Hours per day for one operation, and the time of day (hours) it finishes on its last day.

        `after` = time of day on `earliest` when the previous route step finishes: this step can't start
        before it (route order is strict), and the machine works its queue in order through the day.
        """
        need = step.setup + step.run
        alloc: dict[date, float] = {}
        end = after
        if need <= EPS:
            return {next_working(earliest, f): 0.0}, after
        if finish_by is not None:
            window = days_in(earliest, finish_by, f) or [next_working(finish_by, f)]
            for d in window:
                begin = max(used[(step.machine, d)], after if d == earliest else 0.0)
                take = min(max(avail(step.machine, d) - begin, 0.0), need)
                if take > EPS:
                    alloc[d] = take
                    need -= take
                    end = begin + take
                    clock[(step.machine, d)] = max(clock[(step.machine, d)], end)
            if need > EPS:  # squeeze the rest in: this is a forced overload
                overflow[current[0]] += need
                share = need / len(window)
                for d in window:
                    alloc[d] = alloc.get(d, 0.0) + share
        else:
            d = earliest
            for _ in range(HORIZON_DAYS):
                if is_working(d, f):
                    begin = max(used[(step.machine, d)], after if d == earliest else 0.0)
                    take = min(max(avail(step.machine, d) - begin, 0.0), need)
                    if take > EPS:
                        alloc[d] = take
                        need -= take
                        end = begin + take
                        clock[(step.machine, d)] = max(clock[(step.machine, d)], end)
                        if need <= EPS:
                            break
                d += timedelta(1)
        squeezed = finish_by is not None and need > EPS
        for d, h in alloc.items():
            used[(step.machine, d)] += h
            capacity(step.machine, d)
        if squeezed and earliest in alloc and after > EPS:
            # forced into fewer clock hours than the day has: it can't start before the previous step ends
            key = (step.machine, earliest)
            used[key] = max(used[key], after + alloc[earliest])
        return alloc, end

    def run_job(job: Job, earliest: date, ready: date, finish_by: date | None) -> Placed:
        steps = []
        current[0] = job.id
        at = max(earliest, ready)
        after = 0.0  # step k starts only when step k-1 has finished (same day, later hours, or a later day)
        for st in job.steps:
            alloc, after = place(st, at, finish_by, after)
            steps.append(alloc)
            if alloc and max(alloc) != at:
                at = max(alloc)
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
                                      "until": arrives, "express": mid in express,
                                      "on_order": m.arrival_date})  # fmt: skip
            if rest > EPS:
                # Not in stock and nothing on order. With the express fix the plan assumes an express PO:
                # it arrives express_days after it is ordered (the actual request day, else today), and
                # the order can't start before. Without it the shortfall stays a bottleneck.
                due = None
                if mid in express:
                    due = next_working(inp.ordered.get(mid, today) + timedelta(m.express_days), f)
                    r = max(r, due)
                shortages.append({"kind": "short", "material": mid, "qty": rest, "job": j.id,
                                  "express": mid in express, "arrives": due})  # fmt: skip
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
    return Sched(placed, used, cap, normal, shortages, blocked, dict(overflow), dict(clock), night_days)


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


def hrs(h: float) -> str:
    """'1 hr', '2.5 hrs', '15 hrs'."""
    v = f"{h:.0f}" if h >= 10 else f"{h:.1f}".rstrip("0").rstrip(".")
    return f"{v} hr" if v == "1" else f"{v} hrs"


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
        # Production window: earliest planned start to latest planned finish (calendar days).
        start = min(r["start"] for r in rows)
        end = max(r["finish"] for r in rows)
        # Utilisation: all scheduled machine hours (incl. running orders) / all available capacity hours
        # across the window (Sundays, holidays and downtime have no capacity).
        span = days_in(start, end, f)
        cap_sum = sum(_cap(f, s, m, d) for m in f.machines for d in span)
        use_sum = sum(s.used.get((m, d), 0.0) for m in f.machines for d in span)
        util = round(100 * use_sum / cap_sum) if cap_sum else 0
        length = (end - start).days + 1
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
            opened = s.night_days.get(fx, set())
            for (mm, d), used_h in s.used.items():
                if (mm, d) in opened:
                    h = max(used_h, s.clock.get((mm, d), 0.0))
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
            target = next((j.number for j in jobs if j.id == night_target(fx)), None)
            label = f"Night shift on {m.name}" + (f" for {target}" if target else "") + (
                f" · {_fmt_range(rng[0][0], rng[-1][1])}" if rng else "")  # fmt: skip
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
                     "late_days": a["rows"][j.id]["late_days"],
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
        "min_margin": rules.min_margin_pct,
        "penalty_rule": {"mode": rules.penalty_mode, "value": rules.penalty_value},
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


def keep_locked(new: list[str], old: list[str], locks: dict[str, date] | dict[str, Any]) -> list[str]:
    """`new` (e.g. sorted by a rule) with every locked order put back in the slot it had in `old`."""
    slots = {old.index(j): j for j in locks if j in old and j in new}
    rest = [x for x in new if x not in slots.values()]
    out: list[str] = []
    for k in range(len(new)):
        out.append(slots.pop(k) if k in slots else rest.pop(0) if rest else "")
    out = [x for x in out if x] + [slots[k] for k in sorted(slots)]
    return out


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
            if new == seq or any(new.index(lk) != seq.index(lk) for lk in inp.locks if lk in seq):
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
    b = ev.a["rows"][before]
    dl = _job(jobs, before).deadline
    if b["late_days"]:
        effect += f" {num[before]} then finishes {_fmt_day(b['finish'])}, {b['late_days']} day{'s' * (b['late_days'] != 1)} late."
    else:
        still = "still finishes" if b["finish"] <= cur.a["rows"][before]["finish"] else "finishes"
        gap = b["buffer"]
        effect += (f" {num[before]} {still} {_fmt_day(b['finish'])}, "
                   + (f"{gap} day{'s' * (gap != 1)} before its deadline." if gap else f"on its deadline ({_fmt_day(dl)})."))  # fmt: skip
    if ev.a["days"] != cur.a["days"]:
        effect += f" Plan length {cur.a['days']} → {ev.a['days']} days."
    else:
        effect += f" Plan length stays {ev.a['days']} days."
    title = f"Run {num[moved]} before {num[before]}"
    return {"sequence": new, "title": title, "text": effect, "moved": moved}


def suggest_fixes(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, cur: Eval,
                  today: date) -> list[dict[str, Any]]:  # fmt: skip
    """Night shifts for late orders, express delivery for missing material.

    Judged in the CURRENT plan, not on their own: a fix's effect is the plan with every chosen fix compared
    with the same plan without that one (so picking another fix, or reordering, updates what each one does).
    A night shift is an intent for one order (`night:<machine>:for:<order>`): the engine finds its days again
    on every recalculation and only that order may use the extra hours.
    """
    chosen = set(inp.fixes)
    cache: dict[frozenset[str], Eval] = {frozenset(chosen): cur}

    windows = dict(inp.night_windows)

    def ev(fixes: set[str]) -> Eval:
        k = frozenset(fixes)
        if k not in cache:
            for fx in fixes:
                if night_target(fx) and fx not in windows:  # a suggested shift: its own days in this plan
                    win = resolve_night(
                        f, rules, running, jobs, replace(inp, night_windows=windows), today, fx
                    )
                    if win:
                        windows[fx] = win
            cache[k] = evaluate(f, rules, running, jobs, replace(inp, fixes=set(fixes), night_windows=windows),
                                today)  # fmt: skip
        return cache[k]

    # candidates: express for missing material (as if no fix was chosen); night shifts for every order that
    # is late without any night shift, on each machine of its route
    cands = set(chosen)
    for b in ev(set()).a["bottlenecks"]:
        if b["kind"] in ("material", "material_wait"):
            cands.add(f"express:{b['material']}")
    for b in ev({x for x in chosen if not x.startswith("night:")}).a["bottlenecks"]:
        if b["kind"] == "late":
            j = _job(jobs, b["orders"][0])
            cands |= {f"night:{st.machine}:for:{j.id}" for st in j.steps if st.machine in f.machines}

    out = []
    for fx in sorted(cands):
        w, wo = ev(chosen | {fx}), ev(chosen - {fx})
        status, effect = _fix_effect(f, fx, wo, w, jobs)
        if fx not in chosen and status in ("no_effect", "not_needed"):
            continue  # not worth suggesting in this plan
        info = w.fixes.get(fx, {"label": fx, "cost": 0})
        solved = [
            b["title"]
            for b in wo.a["bottlenecks"]
            if b["title"] not in {x["title"] for x in w.a["bottlenecks"]}
        ]
        out.append({"id": fx, "label": info["label"], "cost": info["cost"],
                    "penalty_avoided": wo.fin["penalty"] - w.fin["penalty"], "solves": solved,
                    "selected": fx in chosen, "status": status, "effect": effect})  # fmt: skip
    # every machine of a late order's route that helps is offered (the owner picks), each with its own effect
    keep = out
    return sorted(keep, key=lambda x: x["label"])


def resolve_night(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, today: date,
                  fx: str) -> tuple[date, date] | None:  # fmt: skip
    """The fewest night shifts, as close to the order's deadline as possible, that put it on time.

    Tries 1, 2, 3... working days ending on the deadline, with the plan's other fixes in place. If none is
    enough, the window that leaves the order least late (then the shortest). Worked out on every recalculation,
    so the shift follows the order when anything else moves it."""
    t = night_target(fx)
    j = next((x for x in jobs if x.id == t), None)
    if j is None:
        return None
    days = days_in(inp.start, max(inp.start, j.deadline), f)
    if not days:
        return None
    best: tuple[tuple[int, int], tuple[date, date]] | None = None
    for k in range(1, len(days) + 1):
        win = (days[-k], days[-1])
        trial = replace(inp, fixes=set(inp.fixes) | {fx}, night_windows={**inp.night_windows, fx: win})
        late = int(evaluate(f, rules, running, jobs, trial, today).a["rows"][j.id]["late_days"])
        if late == 0:
            return win
        if best is None or (late, k) < best[0]:
            best = ((late, k), win)
    return best[1] if best else None


def _upgrade_night(fx: str, f: Factory, jobs: list[Job]) -> str | None:
    """Older plans saved night shifts as fixed date windows made for one late order (window ends on its
    deadline). Turn them into that order's intent; drop an intent whose order left the plan."""
    p = fx.split(":")
    if p[0] != "night" or len(p) != 4:
        return fx
    if p[2] == "for":
        return fx if any(j.id == p[3] for j in jobs) else None
    hits = [j for j in jobs if j.deadline.isoformat() == p[3] and any(st.machine == p[1] for st in j.steps)]
    return f"night:{p[1]}:for:{hits[0].id}" if len(hits) == 1 else fx


def _fix_effect(f: Factory, fx: str, wo: Eval, w: Eval, jobs: list[Job]) -> tuple[str, str]:
    """What a fix does in this plan: status (resolves | partly | no_effect | not_needed | planned) and a line."""
    num = {j.id: j.number for j in jobs}

    def late(e: Eval, jid: str) -> int:
        return int(e.a["rows"].get(jid, {}).get("late_days", 0))

    def days(n: int) -> str:
        return f"{n} day{'s' * (n != 1)}"

    target = night_target(fx)
    if target is not None:
        a, b = late(wo, target), late(w, target)
        o = num.get(target, "the order")
        if a == 0:
            return "not_needed", f"Not needed: {o} is on time without it"
        if b == 0:
            return "resolves", f"Resolves: {o} on time (was {days(a)} late)"
        if b < a:
            return "partly", f"Not enough: {o} still {days(b)} late (was {days(a)})"
        return "no_effect", f"No effect: {o} still {days(b)} late"
    if fx.startswith("express:"):
        mid = fx.split(":", 1)[1]
        mat = f.materials.get(mid)
        name = mat.name if mat else "material"
        had = any(x["kind"] == "material" and x.get("material") == mid for x in wo.a["bottlenecks"])
        line = f"Covers the {name} shortage with an express PO (planned: the PO still has to be raised)"
        moved = [(j, late(wo, j), late(w, j)) for j in w.a["rows"] if late(w, j) != late(wo, j)]
        for jid, a, b in moved:
            if b > a:
                line += f" · {num.get(jid, '')} {days(b)} late while it waits for the express delivery"
        return ("planned" if had else "not_needed"), (line if had else f"Not needed: no {name} shortage")
    # older fixed-window night shift: judged on all late days
    a, b = (
        sum(r["late_days"] for r in wo.a["rows"].values()),
        sum(r["late_days"] for r in w.a["rows"].values()),
    )
    if a == 0:
        return "not_needed", "Not needed: every order is on time without it"
    if b == 0:
        return "resolves", "Resolves: every order on time"
    return ("partly", f"Not enough: still {days(b)} late in total") if b < a else ("no_effect", "No effect")


def constraints(f: Factory, rules: Rules, running: list[Job], jobs: list[Job], inp: Inputs, ev: Eval,
                today: date) -> list[dict[str, Any]]:  # fmt: skip
    """Machine hours missing to deliver the late orders on time.

    The scheduler never books a machine above its hours: an order that competes for a busy machine waits,
    and ships late. To size that, re-plan with each late order forced to finish by its deadline (when its
    material is there in time); the overload that would take, per machine and days, is the constraint:
    "CNC 01 over capacity by 15 hrs, 19-20 Nov".
    """
    late = {j.id: j.deadline for j in jobs
            if ev.a["rows"][j.id]["late_days"] and ev.sched.placed[j.id].material_ready <= j.deadline}  # fmt: skip
    if not late:
        return []
    forced = evaluate(f, rules, running, jobs, replace(inp, pins={**inp.pins, **late}), today)
    fs = forced.sched
    by_m: dict[str, dict[str, Any]] = {}
    for jid in late:
        j = _job(jobs, jid)
        # machine hours the on-time version of this order can't fit into the working time before its deadline
        extra = fs.overflow.get(jid, 0.0) - ev.sched.overflow.get(jid, 0.0)
        if extra <= 0.05:
            continue
        # the machine it queued for: the route step that waited longest after it could have started
        p = ev.sched.placed[jid]
        ready, blame, wait = p.material_ready, None, -1
        for st, alloc in zip(j.steps, p.steps, strict=False):
            if not alloc:
                continue
            could = max(ready, inp.start)
            w = working_days(could, min(alloc), f)
            if w > wait:
                blame, wait = (st.machine, could, min(alloc)), w
            ready = max(alloc)
        if blame is None:
            continue
        m, a, b = blame
        if wait:  # the days it queued: up to the last working day before it got the machine
            b -= timedelta(1)
            while not is_working(b, f) and b > a:
                b -= timedelta(1)
            b = max(a, b)
        c = by_m.setdefault(m, {"kind": "constraint", "resource": f.machines[m].name, "machine": m,
                                "from": a, "to": b, "size": 0.0, "orders": []})  # fmt: skip
        c["from"], c["to"] = min(c["from"], a), max(c["to"], b)
        c["size"] = round(c["size"] + extra, 1)
        c["orders"].append(jid)
    return [c | {"title": f"{c['resource']} over capacity by {hrs(c['size'])}", "text": _fmt_range(c["from"], c["to"])}
            for c in by_m.values()]  # fmt: skip


def feasibility(f: Factory, bottlenecks: list[dict[str, Any]], num: dict[str, str]) -> list[dict[str, Any]]:
    """Plain lines for the feasibility card: red = a resource problem, amber = a late delivery."""
    lines = []
    for b in bottlenecks:
        k = b["kind"]
        who = ", ".join(num.get(i, "") for i in b["orders"])
        if k in ("constraint", "machine"):
            word = "over capacity" if k == "constraint" else "overloaded"
            text = f"{b['resource']} {word} by {hrs(b['size'])}, {_fmt_range(b['from'], b['to'])}"
        elif k == "labour":
            text = f"{b['resource']} labour short by {hrs(b['size'])}, {_fmt_range(b['from'], b['to'])}"
        elif k == "material":
            unit = f.materials[b["material"]].unit
            text = f"{b['resource'][:1].upper()}{b['resource'][1:]} short by {_qty(b['size'], unit)} · affects {who}"
        elif k == "material_wait":
            text = f"{who} waits for {b['resource']} until {_fmt_day(b['from'])}"
        else:
            text = b["title"]
        lines.append({"kind": k, "tone": "warn" if k == "late" else "bad", "text": text, "orders": b["orders"],
                      "machine": b["resource"] if k in ("constraint", "machine") else None})  # fmt: skip
    return lines


def chips(f: Factory, problems: list[dict[str, Any]], num: dict[str, str]) -> list[dict[str, Any]]:
    """Problem chips above the production schedule (red = machine/labour, amber = material)."""
    out = []
    for b in problems:
        k = b["kind"]
        nums = [num.get(i, "") for i in b["orders"]]
        who = " & ".join(nums)
        if k == "constraint":
            title = f"{b['resource']} over capacity"
            text = f"{_fmt_range(b['from'], b['to'])} · +{hrs(b['size'])} · {who} {'waits' if len(nums) == 1 else 'wait'}"
        elif k == "machine":
            title = f"{b['resource']} overloaded"
            text = f"{_fmt_range(b['from'], b['to'])} · +{hrs(b['size'])}" + (
                f" · {who} overlap" if len(nums) > 1 else f" · {who}" if nums else "")  # fmt: skip
        elif k == "material":
            unit = f.materials[b["material"]].unit
            title = f"{b['resource'][:1].upper()}{b['resource'][1:]} short {_qty(b['size'], unit)}"
            text = f"needed {_fmt_day(b['from'])} for {who}"
        elif k == "late":
            continue
        else:
            title, text = b["title"], b["text"]
        out.append(
            {"kind": k, "tone": "warn" if k.startswith("material") else "bad", "title": title, "text": text}
        )
    return out


def _cap(f: Factory, s: Sched, m: str, d: date) -> float:
    if (m, d) in s.cap:
        return s.cap[(m, d)]
    return max(0.0, f.machines[m].hours_per_day - f.downtime.get((m, d), 0.0)) if is_working(d, f) else 0.0


def running_window(ev: Eval, running: list[Job]) -> tuple[date, date] | None:
    """The dates the running (locked) orders are on the floor."""
    if not running:
        return None
    ps = [ev.sched.placed[j.id] for j in running]
    return min(p.start for p in ps), max(p.finish for p in ps)


def _idle(f: Factory, ev: Eval, running: list[Job], today: date) -> list[tuple[str, date]]:
    """(machine, day) with zero scheduled hours on production machines (not QC) during the running window."""
    win = running_window(ev, running)
    if win is None:
        return []
    return [(m.name, d) for d in days_in(win[0], win[1], f) for m in f.machines.values()
            if not m.inspection and _cap(f, ev.sched, m.id, d) > EPS
            and ev.sched.used.get((m.id, d), 0.0) <= EPS]  # fmt: skip


def objective(rules: Rules, ev: Eval, idle_days: int) -> tuple[Any, ...]:
    """The 'Best score' key (smaller is better), built from the company's ordered criteria."""
    late_days = sum(r["late_days"] for r in ev.a["rows"].values())
    parts = {
        "late": (ev.late, late_days),
        "idle": (idle_days,),
        # Contribution per production day over ONE window shared by all options (else a tiny plan always
        # "wins" per day); with the window fixed, that ranks like total contribution.
        "per_day": (-ev.fin["contribution"],),
        "contribution": (-ev.fin["contribution"],),
        "bottlenecks": (ev.problems,),
        "days": (ev.a["days"],),
    }
    return tuple(x for c in rules.criteria if c in parts for x in parts[c])


def _option_metrics(f: Factory, ev: Eval, running: list[Job], ids: list[str], today: date,
                    by: dict[str, Job], idle_before: set[str] | None = None) -> dict[str, Any]:  # fmt: skip
    """`idle_before` = machines idle during the running window in Your selection: an order that starts on
    one of them is shown as filling an idle machine."""
    win = running_window(ev, running)
    alongside = sum(1 for i in ids if win and win[0] <= ev.a["rows"][i]["start"] <= win[1])
    idle = _idle(f, ev, running, today)
    return {"orders": ids, "value": ev.fin["value"], "start": ev.a["start"], "end": ev.a["end"],
            "days": ev.a["days"], "alongside": alongside, "idle_days": len(idle),
            "idle_machines": sorted({n for n, _ in idle}), "utilisation": ev.a["utilisation"],
            "bottlenecks": ev.problems, "bottleneck_names": [b["resource"] for b in ev.a["bottlenecks"]
                                                              if b["kind"] != "late"],
            "late": [i for i in ids if ev.a["rows"][i]["late_days"]],
            "contribution": ev.fin["contribution"], "margin": ev.fin["margin"], "per_day": ev.fin["per_day"],
            "rows": {i: {"start": ev.a["rows"][i]["start"], "finish": ev.a["rows"][i]["finish"],
                         "late_days": ev.a["rows"][i]["late_days"],
                         "route": [f.machines[st.machine].name for st in by[i].steps if st.machine in f.machines],
                         "idle_fill": bool(by[i].steps) and f.machines[by[i].steps[0].machine].name in (
                             idle_before if idle_before is not None else {n for n, _ in idle})}
                     for i in ids},
            "dropped": {}}  # fmt: skip


def options(f: Factory, rules: Rules, running: list[Job], cands: list[Job], selected: list[str], inp: Inputs,
            today: date) -> dict[str, Any]:  # fmt: skip
    """The three selection options, on the same running-order baseline, calendar, stock and costing.

    own  = only the ticked orders (earliest-deadline order).
    part = never drops a ticked order; re-sequences them to remove avoidable late deliveries, then adds
           accepted orders that fit (no new late delivery or bottleneck).
    full = every subset of the accepted orders, each with its best sequence: zero late deliveries and zero
           bottlenecks first (or the fewest, if nothing is clean), then the company's "Best score" rule.
    """
    by = {j.id: j for j in cands}
    cache: dict[tuple[str, ...], Eval] = {}

    def ev_seq(seq: tuple[str, ...]) -> Eval:
        if seq not in cache:
            cache[seq] = evaluate(
                f, rules, running, [by[i] for i in seq], Inputs(inp.start, list(seq)), today
            )
        return cache[seq]

    def seq_key(ev: Eval) -> tuple[Any, ...]:
        late_days = sum(r["late_days"] for r in ev.a["rows"].values())
        return (ev.late, late_days, ev.problems, -ev.fin["contribution"], ev.a["days"])

    def best_sequence(ids: list[str], swaps: bool = True) -> tuple[tuple[str, ...], Eval]:
        """Best order to run a set in: deadline / slack / shortest-first heuristics, then pairwise swaps."""
        if not ids:
            return (), ev_seq(())
        hours = {i: sum(st.setup + st.run for st in by[i].steps) for i in ids}
        starts = {
            tuple(sorted(ids, key=lambda i: (by[i].deadline, by[i].number))),  # earliest due date
            tuple(
                sorted(
                    ids,
                    key=lambda i: (working_days(inp.start, by[i].deadline, f) - hours[i] / 16, by[i].number),
                )
            ),  # slack
            tuple(sorted(ids, key=lambda i: (hours[i], by[i].number))),  # shortest first
        }
        best = min(starts, key=lambda q: seq_key(ev_seq(q)))
        improved = swaps
        while improved:  # swap any two orders while it helps
            improved = False
            for x in range(len(best)):
                for y in range(x + 1, len(best)):
                    q = list(best)
                    q[x], q[y] = q[y], q[x]
                    if seq_key(ev_seq(tuple(q))) < seq_key(ev_seq(best)):
                        best, improved = tuple(q), True
        return best, ev_seq(best)

    def score(ev: Eval) -> tuple[Any, ...]:
        return objective(rules, ev, len(_idle(f, ev, running, today)))

    own = [i for i in selected if i in by]
    # Your selection runs in the plan's own order (its sequencing rule, e.g. highest value first).
    own_seq = tuple([i for i in inp.sequence if i in own] + [i for i in own if i not in inp.sequence])

    # Partly optimized: keep every ticked order; best sequence; then add what fits.
    part_seq, part_ev = best_sequence(own)
    others = sorted((c for c in by if c not in own),
                    key=lambda c: -(by[c].value - job_cost(f, rules, by[c])["total"]))  # most contribution first  # fmt: skip
    for c in others:
        trial_seq, trial_ev = best_sequence([*part_seq, c])
        no_worse = trial_ev.late <= part_ev.late and trial_ev.problems <= part_ev.problems
        if no_worse and trial_ev.fin["contribution"] > part_ev.fin["contribution"]:
            part_seq, part_ev = trial_seq, trial_ev

    # Fully optimized: every non-empty subset of the accepted orders (each with its best sequence).
    # shortcut: exhaustive over at most FULL_POOL orders (2^10 subsets); beyond that the pool is your
    # ticked orders plus the candidates earning the most per machine-hour. Revisit with a MIP solver if
    # a company routinely plans more than ~10 accepted orders at once.
    def per_hour(i: str) -> float:
        hrs = sum(st.setup + st.run for st in by[i].steps) or 1.0
        return (by[i].value - job_cost(f, rules, by[i])["total"]) / hrs

    ranked = own + sorted((c for c in by if c not in own), key=lambda c: -per_hour(c))
    pool = sorted(ranked[:FULL_POOL])

    def full_key(ev: Eval) -> tuple[Any, ...]:
        return (ev.late, ev.problems, *score(ev))  # clean plans first, then the Best-score rule

    # Phase 1: every subset with the quick sequencing rules. Phase 2: pairwise swaps on the best few.
    quick = []
    for mask in range(1, 1 << len(pool)):
        ids = [pool[k] for k in range(len(pool)) if mask >> k & 1]
        q, ev = best_sequence(ids, swaps=False)
        quick.append((full_key(ev), q))
    quick.sort()
    refined = [(full_key(ev), q) for q, ev in (best_sequence(list(q)) for _, q in quick[:FULL_REFINE])]
    full_seq = min(refined)[1] if refined else ()

    out: dict[str, Any] = {}
    own_ev = ev_seq(own_seq) if own_seq else None
    scores: dict[str, tuple[Any, ...]] = {}
    for name, seq in (("own", own_seq), ("part", part_seq), ("full", full_seq)):
        if not seq:
            out[name] = None
            continue
        ev = ev_seq(seq)
        ids = sorted(seq, key=lambda i: (ev.a["rows"][i]["start"], ev.a["rows"][i]["finish"], by[i].number))
        own_idle = {n for n, _ in _idle(f, own_ev, running, today)} if own_ev is not None else None
        m = _option_metrics(f, ev, running, ids, today, by, own_idle)
        cons = constraints(f, rules, running, [by[i] for i in seq], Inputs(inp.start, list(seq)), ev, today)
        m["bottlenecks"] += len(cons)
        m["bottleneck_names"] = [b["resource"] for b in cons] + m["bottleneck_names"]
        m["sequence"] = list(seq)
        if own_ev is not None:
            m["dropped"] = {i: _why_left_out(f, rules, by[i], own_ev) for i in own if i not in seq}
        out[name] = m
        scores[name] = (ev.late, ev.problems, *score(ev))  # the same ranking the optimizer uses
    out["best"] = min(scores, key=lambda k: scores[k]) if scores else None
    out["criteria"] = list(rules.criteria)
    return out


def _current_machine(f: Factory, j: Job, p: Placed, today: date) -> str:
    """The machine a running/booked order is on now (or will be on next)."""
    for st, alloc in zip(j.steps, p.steps, strict=False):
        if alloc and max(alloc) >= today and st.machine in f.machines:
            return f.machines[st.machine].name
    return f.machines[j.steps[0].machine].name if j.steps and j.steps[0].machine in f.machines else ""


def _why_left_out(f: Factory, rules: Rules, j: Job, own: Eval) -> str:
    """Plain reasons, from the numbers, why the optimizer leaves one of your orders out."""
    why = []
    cost = job_cost(f, rules, j)["total"]
    if j.value and 100 * (j.value - cost) / j.value < rules.min_margin_pct:
        why.append("low margin")
    short = {f.materials[sh["material"]].name.lower() for sh in own.sched.shortages if sh["job"] == j.id}
    if short:
        why.append("short of " + ", ".join(sorted(short)))
    if own.a["rows"].get(j.id, {}).get("late_days"):
        why.append("ships late")
    late_machines = {
        st.machine for b in own.a["bottlenecks"] if b["kind"] == "late"
        for k in own.sched.placed if k in b["orders"] for st in own.sched.placed[k].job.steps
    }  # fmt: skip
    busy = [
        f.machines[st.machine].name
        for st in j.steps
        if st.machine in late_machines and st.machine in f.machines
    ]
    if busy and "ships late" not in why:
        why.append(f"crowds {busy[0]}")
    return ", ".join(why) or "earns less per production day"


# ---- the one result every tab reads ---------------------------------------------------------


def _need_text(n: dict[str, Any], today: date) -> str:
    """One line per material for the readiness checklist and the approval popup (one source of truth).
    Says plainly what is a plan assumption (a fix) and what is an actual purchasing record."""
    qty = f"{_qty(n['qty'], n['unit'])} {n['name']}"
    who = ", ".join(n["orders"])
    need = f"needed {_fmt_day(n['needed_by'])} for {who}"
    sup = f" from {n['supplier']}" if n["supplier"] else ""
    req = n["request"]
    act = n["action"]
    if act is None:
        return f"{qty} already on order, arriving {_fmt_day(n['arrives'])} · {who} can't start before"
    kind = {"express_po": "Express PO", "po": "PO", "expedite": "Expedite request"}[act]
    if req:
        eta = f"expected {_fmt_day(n['arrives'])}" if n["arrives"] else "arrival date not confirmed yet"
        po = req.get("po")
        state = {"requested": "waiting for Purchasing to raise the PO",
                 "po_raised": f"{po} awaiting approval, not received yet",
                 "ordered": f"{po} ordered, not received yet",
                 "confirmed": f"{po} confirmed by the supplier, not received yet",
                 "received": f"{po} received"}.get(req["status"], req["status"])  # fmt: skip
        return f"{kind} for {qty} requested {_fmt_day(req['at'])} · {state} · {eta} · {need}"
    if act == "express_po":
        return (f"{kind} for {qty}{sup} not raised yet · planned fix, not ordered: arrives "
                f"{_fmt_day(n['arrives'])} if ordered today · {need}")  # fmt: skip
    if act == "expedite":
        return (f"{kind}{sup} not sent yet · {qty} is on order for {_fmt_day(n['on_order'])}; planned fix: "
                f"brought forward to {_fmt_day(n['arrives'])} · {need}")  # fmt: skip
    return f"{kind} for {qty} not raised yet · not in stock and nothing on order · {need}"


def _iso(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {(k.isoformat() if isinstance(k, date) else k): _iso(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_iso(x) for x in v]
    return v


def compute(f: Factory, rules: Rules, running: list[Job], cands: list[Job], selected: list[str], rule: str,
            inp: Inputs, today: date, requested: dict[str, dict[str, Any]] | set[str],
            opts: dict[str, Any] | None = None, base: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    """Everything the 5 tabs show, from one set of inputs.

    `selected` = the ticked orders the plan is built from; `base` = the owner's own picks the optimizer
    starts from (differs from `selected` after "Use this selection"); `opts` reuses unchanged options.
    """
    # purchasing records for this plan: material id -> {status, at (request day), express, qty}
    if isinstance(requested, set):
        requested = {m: {"status": "requested", "at": today, "express": False, "qty": 0.0} for m in requested}
    inp.ordered = {m: r["at"] for m, r in requested.items()}
    by = {j.id: j for j in cands}
    jobs = [by[i] for i in selected if i in by]
    inp.sequence = keep_locked(by_rule(rule, jobs, f, rules, inp.sequence), inp.sequence, inp.locks)
    inp.locks = {k: v for k, v in inp.locks.items() if k in inp.sequence}
    inp.pins = {k: v for k, v in inp.pins.items() if k in inp.sequence}
    inp.fixes = {x for x in (_upgrade_night(fx, f, jobs) for fx in inp.fixes) if x}
    inp.night_windows = {}
    for fx in sorted(x for x in inp.fixes if night_target(x)):
        win = resolve_night(f, rules, running, jobs, inp, today, fx)
        if win:
            inp.night_windows[fx] = win
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
                     "machines": [f.machines[s.machine].name for s in j.steps],
                     "machine": _current_machine(f, j, cur.sched.placed[j.id], today)} for j in running]  # fmt: skip
    if opts is None:
        opts = _iso(options(f, rules, running, cands, base if base is not None else selected, inp, today))
    # Which option is in use: the one whose orders are exactly the ticked orders.
    using = next((k for k in ("own", "part", "full")
                  if opts.get(k) and set(opts[k]["orders"]) == set(selected)), None)  # fmt: skip

    # Tab 2 --------------------------------------------------------------------------------
    cons = constraints(f, rules, running, jobs, inp, cur, today) if jobs else []
    over_machines = {
        b["resource"] for b in [*cons, *a["bottlenecks"]] if b["kind"] in ("machine", "constraint")
    }
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
    problems = [*cons, *a["bottlenecks"]]
    groups = [g | {"conflict": [m for m in g["shared"] if m in over_machines]} for g in a["groups"]]
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
                          "setup": 0.0 if j.running else st.setup})  # fmt: skip
        over_days = sorted({d for st in steps for d in st["hours"]
                            if cur.sched.used[(st["machine"], d)] > cur.sched.cap[(st["machine"], d)] + EPS})  # fmt: skip
        wait = [
            {"machine": c["resource"], "from": c["from"], "to": c["to"]} for c in cons if j.id in c["orders"]
        ]
        gantt.append({"id": j.id, "running": j.running, "steps": steps, "start": p.start, "finish": p.finish,
                      "wait": wait,
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
    # What purchasing has to do for this plan, per material, against actual stock and deliveries on order:
    #   po         not in stock, nothing on order            -> raise a PO
    #   express_po same, and the plan chose the express fix  -> raise an express PO (a plan assumption until raised)
    #   expedite   on order but arrives late, express fix    -> ask the supplier to bring the delivery forward
    #   None       on order, the order just waits for it     -> nothing to raise
    need_rank = {None: 0, "expedite": 1, "po": 2, "express_po": 3}
    needs: dict[str, dict[str, Any]] = {}
    for sh in cur.sched.shortages:
        if sh["job"] not in a["rows"]:
            continue
        mat = f.materials[sh["material"]]
        action: str | None
        if sh["kind"] == "short":
            action = "express_po" if sh["express"] else "po"
        else:
            action = "expedite" if sh["express"] else None
        req = requested.get(mat.id)
        n = needs.setdefault(mat.id, {"material": mat.id, "code": mat.code, "name": mat.name, "unit": mat.unit, "qty": 0.0,
                                    "needed_by": sh["needed_by"], "orders": [], "express": sh["express"],
                                    "kind": sh["kind"], "action": action, "arrives": None, "on_order": None,
                                    "supplier": mat.supplier, "requested": req is not None, "request": req})  # fmt: skip
        if need_rank[action] > need_rank[n["action"]]:
            n["action"], n["kind"] = action, sh["kind"]
        due = sh.get("arrives") or sh.get("until")
        if due and (n["arrives"] is None or due > n["arrives"]):
            n["arrives"] = due
        n["on_order"] = n["on_order"] or sh.get("on_order")
        n["qty"] = round(n["qty"] + sh["qty"], 3)
        n["needed_by"] = min(n["needed_by"], sh["needed_by"])
        n["orders"].append(num[sh["job"]])
    fin_with, fin_before = cur.fin, before.fin
    min_buf = min(seq, key=lambda x: x["buffer"]) if seq else None
    machine_b = [b for b in a["bottlenecks"] if b["kind"] == "machine"]
    labour_b = [b for b in a["bottlenecks"] if b["kind"] == "labour"]
    to_raise = [n for n in needs.values() if n["action"]]
    open_po = [n for n in to_raise if not n["requested"]]
    on_order = [n for n in needs.values() if not n["action"]]
    mat_items = [{"material": n["material"], "open": n["action"] is not None and not n["requested"],
                  "text": _need_text(n, today)} for n in needs.values()]  # fmt: skip
    mat_title = (f"{len(open_po)} material PO{'s' * (len(open_po) != 1)} not raised yet" if open_po
                 else "Material POs raised · not received yet" if to_raise
                 else "Materials covered by stock and deliveries on order" if on_order
                 else "All materials in stock")  # fmt: skip
    checks: list[dict[str, Any]] = [
        {"ok": not cur.late, "title": f"All {len(jobs)} orders ship on time" if not cur.late
         else f"{cur.late} order{'s ship' if cur.late != 1 else ' ships'} late",
         "text": ("Late: " + ", ".join(f"{num[r['id']]} by {r['late_days']} day{'s' * (r['late_days'] != 1)}"
                                        for r in seq if r["late_days"])) if cur.late
         else (f"Smallest buffer: {num[min_buf['id']]}, {min_buf['buffer']} days" if min_buf else "")},
        {"ok": not machine_b, "title": "Machine capacity within limits" if not machine_b
         else "Machines over capacity", "text": "; ".join(f"{b['resource']} {b['text']}" for b in machine_b)},
        {"ok": not open_po, "title": mat_title, "text": "; ".join(i["text"] for i in mat_items),
         "items": mat_items, "action": "raise_po" if open_po else None},
        {"ok": not labour_b, "title": "Labour and shifts covered" if not labour_b else "Labour short",
         "text": "; ".join(f"{b['resource']} {b['text']}" for b in labour_b)},
        {"ok": fin_with["margin"] >= rules.min_margin_pct,
         "title": f"Margin {'above' if fin_with['margin'] >= rules.min_margin_pct else 'below'} your "
                  f"{rules.min_margin_pct:g}% minimum", "text": f"{fin_with['margin']}% after fixes",
         "setting": "min_margin_pct"},
    ]  # fmt: skip

    lines = feasibility(f, problems, num)
    out: dict[str, Any] = _iso({
        "selection": {"orders": orders, "selected": [i for i in selected if i in by], "running": running_rows,
                      "using": using, "base": [i for i in (base if base is not None else selected) if i in by],
                      "options": opts},
        "sequence": {"rule": rule, "start": inp.start, "rows": seq, "groups": groups, "hint": hint,
                     "overview": {"orders": len(jobs), "start": a["start"], "end": a["end"], "days": a["days"],
                                  "utilisation": a["utilisation"], "on_time": on_time,
                                  "bottlenecks": len([b for b in problems if b["kind"] != "late"]),
                                  "parallel": sum(1 for g in a["groups"] if len(g["orders"]) > 1),
                                  "late": len(jobs) - on_time},
                     "feasibility": {"ok": not problems, "lines": lines}},
        "schedule": {"days": days, "today": today, "rows": gantt, "load": load,
                     "bottlenecks": [b for b in problems if b["kind"] not in ("late", "constraint")],
                     "constraints": cons, "chips": chips(f, problems, num)},
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
        sch = r["schedule"]
        return {f"{b['kind']}:{b['resource']}": b for b in [*sch.get("constraints", []), *sch["bottlenecks"]]}

    o, n = idx(old), idx(new)

    def was(b: dict[str, Any]) -> str:
        if b["kind"] in ("machine", "constraint"):
            a, z = (d if isinstance(d, date) else date.fromisoformat(d) for d in (b["from"], b["to"]))
            return f"+{hrs(b['size'])} on {_fmt_range(a, z)}"
        return str(b["text"])

    worse = [
        b | {"was": was(o[k]) if k in o else None}
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
