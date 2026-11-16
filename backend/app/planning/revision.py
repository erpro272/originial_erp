"""Does an approved plan still hold? Pure functions, no DB.

`basis()` records the business data a plan was calculated on (its orders, the materials and machines they use,
downtime, competing orders, company rules). It is stored in every result, so the approved snapshot carries the
data it was approved on.

`compare()` puts the plan recalculated now next to its last approved version and lists what changed:
  significant (needs re-approval): an order finishes later or becomes late, leaves the plan (cancelled) or its
    quantity / price / ship date changed, a material that was covered is now short, a machine is overloaded, or
    contribution fell by more than the company's limit (`reapproval_margin_drop_pct`);
  info only: improvements (earlier finish, shortage gone, more money) and small money changes.
Each change says why: the data changes (causes) that touch the same orders, materials or machines.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.planning import engine as eng

RULE_LABELS = {
    "penalty_mode": "Late penalty type",
    "penalty_fixed_paise": "Late penalty per day",
    "penalty_percent": "Late penalty %",
    "overhead_pct": "Overheads %",
    "packaging_paise_per_unit": "Packaging per unit",
    "min_margin_pct": "Minimum margin %",
}


def _day(v: Any) -> str:
    d = date.fromisoformat(v) if isinstance(v, str) else v
    return f"{d.day} {d:%b}"


def _num(v: float) -> str:
    return f"{v:,.3f}".rstrip("0").rstrip(".")


def _rupees(p: int) -> str:
    return f"₹{p / 100:,.0f}"


def basis(
    f: eng.Factory,
    jobs: list[eng.Job],
    running: list[eng.Job],
    rules: dict[str, Any],
    order_status: dict[str, str],
) -> dict[str, Any]:
    """The data the plan's numbers depend on, in a form that can be compared later (JSON-safe)."""
    mats = {m for j in jobs for m, _ in j.materials}
    machs = {s.machine for j in jobs for s in j.steps}
    return {
        "orders": {
            j.id: {
                "number": j.number,
                "qty": j.qty,
                "unit": j.unit,
                "value": j.value,
                "deadline": j.deadline.isoformat(),
                "status": order_status.get(j.id),
                "materials": sorted({m for m, _ in j.materials}),
                "machines": sorted({s.machine for s in j.steps}),
            }
            for j in jobs
        },
        "materials": {
            m: {
                "code": x.code,
                "unit": x.unit,
                "on_hand": x.on_hand,
                "price": x.price,
                "arrival": x.arrival_date.isoformat() if x.arrival_date else None,
                "arrival_qty": x.arrival_qty,
            }
            for m in sorted(mats)
            if (x := f.materials.get(m))
        },
        "machines": {
            m: {"name": f.machines[m].name, "hours": f.machines[m].hours_per_day}
            for m in sorted(machs)
            if m in f.machines
        },
        "downtime": sorted([m, d.isoformat(), h] for (m, d), h in f.downtime.items() if m in machs),
        "closed": sorted(d.isoformat() for d in f.closed),
        # orders already booked on the same machines (they go first)
        "competing": sorted(
            [j.id, j.number, sorted({s.machine for s in j.steps} & machs)]
            for j in running
            if {s.machine for s in j.steps} & machs
        ),
        "rules": {k: rules[k] for k in RULE_LABELS if k in rules},
    }


def _cause(
    text: str,
    *,
    orders: Any = (),
    materials: Any = (),
    machines: Any = (),
    money: bool = False,
    kind: str = "data",
) -> dict[str, Any]:
    return {
        "text": text,
        "kind": kind,
        "orders": sorted(orders),
        "materials": sorted(materials),
        "machines": sorted(machines),
        "money": money,
    }


def causes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """What changed in the business data between approval (old basis) and now (new basis)."""
    out: list[dict[str, Any]] = []
    on, nn = old.get("orders", {}), new.get("orders", {})
    for oid, o in on.items():
        n = nn.get(oid)
        if n is None:
            out.append(
                _cause(f"{o['number']} is no longer plannable", orders=[oid], money=True, kind="order")
            )
            continue
        if n.get("status") == "cancelled" and o.get("status") != "cancelled":
            out.append(_cause(f"{o['number']} was cancelled", orders=[oid], money=True, kind="order"))
        if n["qty"] != o["qty"]:
            out.append(
                _cause(
                    f"{o['number']} quantity {_num(o['qty'])} → {_num(n['qty'])} {n['unit']}",
                    orders=[oid],
                    materials=n["materials"],
                    machines=n["machines"],
                    money=True,
                    kind="order",
                )
            )
        if n["value"] != o["value"]:
            out.append(
                _cause(
                    f"{o['number']} order value {_rupees(o['value'])} → {_rupees(n['value'])}",
                    orders=[oid],
                    money=True,
                    kind="order",
                )
            )
        if n["deadline"] != o["deadline"]:
            out.append(
                _cause(
                    f"{o['number']} ship date {_day(o['deadline'])} → {_day(n['deadline'])}",
                    orders=[oid],
                    money=True,
                    kind="order",
                )
            )
    om, nm = old.get("materials", {}), new.get("materials", {})
    for mid, o in om.items():
        n = nm.get(mid)
        if n is None:
            continue
        users = [k for k, v in nn.items() if mid in v["materials"]]
        if abs(n["on_hand"] - o["on_hand"]) > 1e-9:
            out.append(
                _cause(
                    f"{o['code']} stock {_num(o['on_hand'])} → {_num(n['on_hand'])} {o['unit']}",
                    orders=users,
                    materials=[mid],
                )
            )
        if (n["arrival"], n["arrival_qty"]) != (o["arrival"], o["arrival_qty"]):
            if o["arrival"] and not n["arrival"]:
                text = f"{o['code']} delivery of {_num(o['arrival_qty'])} {o['unit']} ({_day(o['arrival'])}) is no longer on order"
            elif n["arrival"] and not o["arrival"]:
                text = f"{o['code']} delivery of {_num(n['arrival_qty'])} {o['unit']} now on order for {_day(n['arrival'])}"
            elif n["arrival"] != o["arrival"]:
                text = f"{o['code']} delivery moved {_day(o['arrival'])} → {_day(n['arrival'])}"
            else:
                text = f"{o['code']} delivery {_num(o['arrival_qty'])} → {_num(n['arrival_qty'])} {o['unit']}"
            out.append(_cause(text, orders=users, materials=[mid]))
        if n["price"] != o["price"]:
            out.append(
                _cause(
                    f"{o['code']} price {_rupees(o['price'])} → {_rupees(n['price'])} per {o['unit']}",
                    orders=users,
                    materials=[mid],
                    money=True,
                )
            )
    oc, nc = old.get("machines", {}), new.get("machines", {})
    names = {**{k: v["name"] for k, v in oc.items()}, **{k: v["name"] for k, v in nc.items()}}

    def users_of(m: str) -> list[str]:
        return [k for k, v in nn.items() if m in v["machines"]]

    for mid, o in oc.items():
        n = nc.get(mid)
        if n is None:
            out.append(_cause(f"{o['name']} is no longer in use", orders=users_of(mid), machines=[mid]))
        elif n["hours"] != o["hours"]:
            out.append(
                _cause(
                    f"{o['name']} hours per day {_num(o['hours'])} → {_num(n['hours'])}",
                    orders=users_of(mid),
                    machines=[mid],
                )
            )
    od = {(m, d): h for m, d, h in old.get("downtime", [])}
    nd = {(m, d): h for m, d, h in new.get("downtime", [])}
    for (m, d), h in sorted(nd.items(), key=lambda x: (x[0][1], x[0][0])):
        if od.get((m, d)) != h:
            verb = "added" if (m, d) not in od else "changed"
            out.append(
                _cause(
                    f"{names.get(m, 'A machine')} downtime {verb} {_day(d)} ({_num(h)} h)",
                    orders=users_of(m),
                    machines=[m],
                )
            )
    for m, d in sorted(set(od) - set(nd), key=lambda x: (x[1], x[0])):
        out.append(
            _cause(
                f"{names.get(m, 'A machine')} downtime removed {_day(d)}", orders=users_of(m), machines=[m]
            )
        )
    for d in sorted(set(new.get("closed", [])) - set(old.get("closed", []))):
        out.append(_cause(f"Factory closed {_day(d)}", orders=list(nn), machines=list(nc)))
    ocp = {c[0]: c for c in old.get("competing", [])}
    ncp = {c[0]: c for c in new.get("competing", [])}
    for cid in sorted(set(ncp) - set(ocp), key=lambda i: ncp[i][1]):
        _, number, shared = ncp[cid]
        out.append(
            _cause(
                f"{number} is now booked first on {', '.join(names.get(m, '?') for m in shared)}",
                orders=[k for k in nn if set(nn[k]["machines"]) & set(shared)],
                machines=shared,
            )
        )
    orr, nr = old.get("rules", {}), new.get("rules", {})
    for k, label in RULE_LABELS.items():
        if k in orr and k in nr and orr[k] != nr[k]:
            fmt = (
                _rupees
                if k.endswith("paise") or k.endswith("_per_unit")
                else (lambda v: f"{v:g}" if isinstance(v, float) else str(v))
            )
            out.append(_cause(f"Company rule: {label} {fmt(orr[k])} → {fmt(nr[k])}", money=True, kind="rule"))
    return out


def _change(
    kind: str,
    significant: bool,
    title: str,
    *,
    orders: Any = (),
    materials: Any = (),
    machines: Any = (),
    money: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "significant": significant,
        "title": title,
        "why": [],
        "_refs": (set(orders), set(materials), set(machines), money),
    }


def _late(n: int) -> str:
    return f"{n} day{'s' * (n != 1)} late"


def compare(approved: dict[str, Any], live: dict[str, Any], margin_drop_pct: float) -> dict[str, Any]:
    """What changed since approval, each with why. `significant` = the owner has to approve it again."""
    ob, nb = approved.get("_basis"), live.get("_basis")
    why = causes(ob, nb) if ob and nb else []
    orders = (nb or ob or {}).get("orders", {})
    num = {
        **{k: v["number"] for k, v in orders.items()},
        **{k: v.get("number", "") for k, v in live.get("selection", {}).get("orders", {}).items()},
    }
    machine_ids = {v["name"]: k for k, v in ((nb or {}).get("machines") or {}).items()}

    def refs_of(oid: str) -> dict[str, Any]:
        o = orders.get(oid, {})
        return {"orders": [oid], "materials": o.get("materials", []), "machines": o.get("machines", [])}

    out: list[dict[str, Any]] = []
    old_rows = {r["id"]: r for r in approved.get("sequence", {}).get("rows", [])}
    new_rows = {r["id"]: r for r in live.get("sequence", {}).get("rows", [])}
    for oid, o in old_rows.items():
        n = new_rows.get(oid)
        name = num.get(oid, "An order")
        if n is None:
            out.append(
                _change("order_removed", True, f"{name} is no longer in the plan", orders=[oid], money=True)
            )
            continue
        of, nf = o["finish"], n["finish"]
        if nf > of:
            late = (
                f" · now {_late(n['late_days'])}"
                if n["late_days"] and not o["late_days"]
                else (
                    f" · {_late(n['late_days'])} (approved: {o['late_days']})"
                    if n["late_days"] > o["late_days"]
                    else ""
                )
            )
            out.append(
                _change(
                    "order_later",
                    True,
                    f"{name} now finishes {_day(nf)} (approved {_day(of)}){late}",
                    **refs_of(oid),
                )
            )
        elif n["late_days"] > o["late_days"]:
            out.append(_change("order_late", True, f"{name} is now {_late(n['late_days'])}", **refs_of(oid)))
        elif nf < of:
            out.append(
                _change(
                    "order_earlier",
                    False,
                    f"{name} now finishes {_day(nf)} (approved {_day(of)})",
                    **refs_of(oid),
                )
            )
    # the order's own data changed (quantity, price, ship date): always the owner's call
    for c in why:
        if c["kind"] == "order" and not any(
            ch["kind"] == "order_removed" and c["orders"] == sorted(ch["_refs"][0]) for ch in out
        ):
            out.append(_change("order_changed", True, c["text"], orders=c["orders"], money=True))

    def need_map(r: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            n["material"]: n for n in r.get("purchase_needs", []) if n.get("action") in ("po", "express_po")
        }

    on, nn = need_map(approved), need_map(live)
    for mid, n in nn.items():
        o = on.get(mid)
        users = [i for i in new_rows if mid in orders.get(i, {}).get("materials", [])]
        if o is None:
            out.append(
                _change(
                    "material_short",
                    True,
                    f"{n['name']} is now short by {_num(n['qty'])} {n['unit']} · "
                    f"affects {', '.join(n['orders'])}",
                    orders=users,
                    materials=[mid],
                )
            )
        elif n["qty"] > o["qty"] + 1e-9:
            out.append(
                _change(
                    "material_short",
                    True,
                    f"{n['name']} short by {_num(n['qty'])} {n['unit']} (approved: {_num(o['qty'])})",
                    orders=users,
                    materials=[mid],
                )
            )
    for mid, o in on.items():
        if mid not in nn:
            out.append(_change("material_ok", False, f"{o['name']} no longer short", materials=[mid]))

    def over(r: dict[str, Any]) -> dict[str, str]:
        return {
            line["machine"]: line["text"]
            for line in r.get("sequence", {}).get("feasibility", {}).get("lines", [])
            if line.get("machine")
        }

    oo, no = over(approved), over(live)
    for m, text in no.items():
        if m not in oo:
            mid = machine_ids.get(m, "")
            out.append(
                _change(
                    "machine_over",
                    True,
                    text,
                    machines=[mid] if mid else [],
                    orders=[i for i in new_rows if mid in orders.get(i, {}).get("machines", [])],
                )
            )
    for m in oo:
        if m not in no:
            out.append(
                _change("machine_ok", False, f"{m} no longer over capacity", machines=[machine_ids.get(m, m)])
            )

    oc = (approved.get("finance", {}).get("with") or {}).get("contribution", 0)
    nc = (live.get("finance", {}).get("with") or {}).get("contribution", 0)
    if nc != oc:
        drop = (oc - nc) / abs(oc) * 100 if oc else (100.0 if nc < oc else 0.0)
        big = drop > margin_drop_pct
        word = "down" if nc < oc else "up"
        out.append(
            _change(
                "money",
                big,
                f"Contribution {word} {_rupees(abs(nc - oc))}: {_rupees(oc)} → {_rupees(nc)}"
                + (f" (more than your {margin_drop_pct:g}% limit)" if big else ""),
                money=True,
            )
        )

    for ch in out:
        o_, m_, mc_, money = ch.pop("_refs")
        if ch["kind"] == "order_changed":
            continue  # it is its own cause
        hits = [
            c["text"]
            for c in why
            if (o_ & set(c["orders"]))
            or (m_ & set(c["materials"]))
            or (mc_ & set(c["machines"]))
            or (money and c["money"])
        ]
        ch["why"] = hits[:6] or ([] if why else ["Stock, factory or order data changed since approval"])
    significant = [c for c in out if c["significant"]]
    return {
        "needed": bool(significant),
        "changes": significant + [c for c in out if not c["significant"]],
        "causes": [c["text"] for c in why],
    }
