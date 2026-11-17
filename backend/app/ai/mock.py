"""Scripted stand-in for the LLM when no ``LLM_API_KEY`` is set (dev without a key, all tests, e2e).

It picks tools with simple rules (like the model would with native tool calling) and answers with the tools'
own one-line summaries, so every number shown still comes from the ERP tools. Deterministic.
"""

import json
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Literal

from app.ai.llm import ChatResult, ToolCall
from app.core import clock

HELP = ("I can answer from live ERP data: machine schedules and load, why an order is late, orders at risk or "
        "ready to ship, the current plan with fixes and what-ifs, capacity for a new order, material coverage, purchase "
        "orders, receivables, payables and cost trends. Try “Is CNC 01 busy tomorrow?” or “Which orders are at risk?”.")  # fmt: skip

HOWTO = re.compile(
    r"\b(how (do|can|does|should|to|are|is the)|can (i|we|the \w+)|where (do|can|is)|explain|logic|"
    r"what does .+ mean|who (can|approves|may)|what can you do|how .+ work|what is (a|the) )",
    re.I,
)
MACHINE = re.compile(r"\b(cnc|press|assembly|rolling|qc|lathe|drill|furnace)[\s-]*(\d+)?\b", re.I)


def _text(m: dict[str, Any]) -> str:
    c = m.get("content")
    return c if isinstance(c, str) else ""


def plan_calls(text: str, names: set[str]) -> list[tuple[str, dict[str, Any]]]:
    t = text.lower()
    today = clock.today()
    monday = today - timedelta(days=today.weekday())
    calls: list[tuple[str, dict[str, Any]]] = []
    orders = [f"ORD-{n}" for n in re.findall(r"ord[\s-]*(\d{3,})", t)]
    mach = MACHINE.search(text)
    if mach and "load" not in t and "utili" not in t:
        name = f"{mach.group(1).upper() if len(mach.group(1)) <= 3 else mach.group(1).title()} {mach.group(2) or ''}".strip()
        start = (
            today + timedelta(days=1)
            if "tomorrow" in t
            else today
            if "today" in t
            else today + timedelta(days=1)
        )
        end = monday + timedelta(days=5) if "week" in t else start
        calls.append(
            ("machine_schedule", {"machine": name, "start": start.isoformat(), "end": end.isoformat()})
        )
    if "night shift" in t and mach:
        calls.append(
            ("simulate_plan", {"night_shift_machine": f"{mach.group(1)} {mach.group(2) or ''}".strip()})
        )
    for o in orders:
        if any(w in t for w in ("delay", "late", "why", "behind", "slip")):
            calls.append(("why_delayed", {"order": o}))
        else:
            calls.append(("order_details", {"order": o}))
    if not orders and any(w in t for w in ("at risk", "risk", "delayed orders", "late orders")):
        calls.append(("orders_at_risk", {}))
    if "ship" in t and not orders:
        calls.append(("shippable_orders", {}))
    if "load" in t or "utili" in t:
        if "last month" in t:
            first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            calls.append(
                (
                    "machine_load",
                    {
                        "start": first.isoformat(),
                        "end": (today.replace(day=1) - timedelta(days=1)).isoformat(),
                    },
                )
            )
        else:
            calls.append(("machine_load", {}))
    if "capacity for" in t or ("capacity" in t and re.search(r"\d", t)):
        q = re.search(r"(\d[\d,]*)\s*(pcs|pieces|units|nos)?", t)
        prod = re.sub(r".*capacity for\s*", "", text, flags=re.I).strip(" ?.")
        prod = (
            re.sub(r"\b\d[\d,]*\s*(pcs|pieces|units|nos)?\b", "", prod).replace("order", "").strip()
            or "bolts"
        )
        calls.append(
            ("capacity_check", {"product": prod, "quantity": int(q.group(1).replace(",", "")) if q else 1000})
        )
    if (
        any(w in t for w in ("material", "enough", "shortage", "stock", "aluminium", "steel", "wire"))
        and "cost" not in t
    ):
        nxt = monday + timedelta(days=7)
        calls.append(("material_coverage", {"start": nxt.isoformat(), "end": (nxt + timedelta(days=6)).isoformat()}
                      if "next week" in t else {}))  # fmt: skip
    if "sequence" in t or "order of" in t:
        calls.append(("best_sequence", {}))
    elif (
        (any(w in t for w in ("fix", "improve", "contribution", "suggest")) and "plan" in t)
        or "what-if" in t
        or "what if" in t
    ):
        calls.append(("plan_fixes", {}))
    elif "plan" in t and not any(c[0] == "simulate_plan" for c in calls):
        calls.append(("plan_summary", {}))
    if any(w in t for w in ("purchase order", " po ", "pos ", "supplier deliver")):
        calls.append(("purchase_orders", {}))
    if re.search(
        r"\b(supplier|vendor)s?\b.*\b(score|scoring|compar|best|recommend|rating|why)|\b(compare|best|recommended) (supplier|vendor)",
        t,
    ):
        calls.append(("supplier_comparison", {}))
    if any(w in t for w in ("receivable", "owe us", "customers owe", "overdue", "collection")):
        calls.append(("receivables", {}))
    if any(w in t for w in ("payable", "we owe", "pay supplier")):
        calls.append(("payables", {}))
    if ("cost" in t and "night" not in t and not re.search(r"\bpolicy\b.*\bcost|costing policy", t)) or (
        "increase" in t and "cost" in t
    ):
        calls.append(("cost_trend", {}))
    if re.search(
        r"\b(polic(y|ies)|sop|procedure|manual|safety|inspection|iso|din|standard|document|lockout|according to|maintenance|ppe|coolant|scrap|overheads?|how often)\b",
        t,
    ):
        dq = re.split(r"(?:what does|what do|according to)\s+(?:our|the)?\s*", text, flags=re.I)[-1]
        dq = re.sub(r"\b(say|says|about|tell us)\b|\?", " ", dq, flags=re.I).strip() or text
        calls.append(("search_documents", {"query": dq[:200]}))
    if not orders and HOWTO.search(t):  # how-to / permission / logic questions about the ERP itself
        calls.insert(0, ("erp_guide", {"question": text[:300]}))
    if not calls:  # a module or topic named on its own ("purchasing", "billing", "stock"...): its overview
        for words, names_ in ((("purchas", "supplier", "po "), ("purchase_orders", "material_coverage")),
                              (("billing", "payment", "money", "cash", "invoice"), ("receivables", "payables")),
                              (("inventory", "stock", "material"), ("material_coverage",)),
                              (("planning", "plan", "schedule"), ("plan_summary",)),
                              (("production", "machine", "factory", "capacity"), ("machine_load",)),
                              (("order", "customer", "ship", "deliver"), ("orders_at_risk", "shippable_orders")),
                              (("business", "today", "overview", "summary", "status", "how are we"),
                               ("plan_summary", "orders_at_risk", "receivables"))):  # fmt: skip
            if any(w in t + " " for w in words):
                calls += [(n, {}) for n in names_]
                break
    seen: set[str] = set()
    out = []
    for name, args in calls:
        key = name + json.dumps(args, sort_keys=True)
        if name in names and key not in seen:
            seen.add(key)
            out.append((name, args))
    return out[:5]


class ScriptedLLM:
    mode: Literal["live", "mock"] = "mock"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        model: str | None = None,
        max_tokens: int = 1024,
        on_wait: Callable[[float], None] | None = None,  # told before waiting out a rate limit
    ) -> ChatResult:
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        results = [m for m in messages[last_user + 1 :] if m.get("role") == "tool"]
        if results:
            lines = []
            for m in results:
                try:
                    lines.append(json.loads(_text(m)).get("summary", ""))
                except json.JSONDecodeError:
                    continue
            lines = [x for x in lines if x]
            text = (
                lines[0]
                if len(lines) == 1
                else "Here's the latest from your ERP data:\n\n" + "\n".join(f"- {x}" for x in lines)
            )
            return ChatResult(content=text, tool_calls=[], model="mock")
        names = {t["function"]["name"] for t in tools or []}
        text = _text(messages[last_user]) if last_user >= 0 else ""
        calls = plan_calls(text, names)
        from app.ai.assistant.tools import BY_NAME

        hidden = [n for n, _ in plan_calls(text, set(BY_NAME)) if n not in names]
        if hidden and not calls:
            return ChatResult(
                content="Your role doesn't have access to the data this question needs.",
                tool_calls=[],
                model="mock",
            )
        if not calls:
            return ChatResult(
                content=HELP if names else "I can't look that up with your role's access.",
                tool_calls=[],
                model="mock",
            )
        return ChatResult(content="", model="mock",
                          tool_calls=[ToolCall(id=f"call_{i}", name=n, args=a) for i, (n, a) in enumerate(calls)])  # fmt: skip
