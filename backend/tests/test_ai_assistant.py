"""AI Assistant (handover A): typed SSE contract, conversations private to their user and company, tools filtered by
role, independent tools run in parallel with timeout / failure isolation, the free-tier rate-limit fallback, and
invoice reading on the vision client. Always the offline scripted model (no key in tests)."""

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.ai import service as ai_service
from app.ai.assistant import graph as g
from app.ai.assistant.tools import BY_NAME, ToolOut
from app.ai.llm import LLMError, OpenAICompatibleLLM, wait_seconds
from app.invoices.normalize import build_document
from tests.conftest import headers_for
from tests.test_purchasing import _demo_co

CHAT = "/ai/chat"


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        ev = next(line[6:].strip() for line in block.splitlines() if line.startswith("event:"))
        data = json.loads(next(line[5:] for line in block.splitlines() if line.startswith("data:")))
        out.append((ev, data))
    return out


async def ask(
    client: AsyncClient, h: dict[str, str], text: str, cid: str | None = None
) -> list[tuple[str, dict[str, Any]]]:
    r = await client.post(CHAT, json={"message": text, "conversation_id": cid}, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return events(r.text)


async def test_chat_streams_typed_events_and_saves_the_conversation(client: AsyncClient) -> None:
    co = await _demo_co("ai1")
    owner = await headers_for(client, co)
    st = (await client.get("/ai/status", headers=owner)).json()
    assert st["mode"] == "mock" and "machine_schedule" in st["tools"] and "receivables" in st["tools"]

    evs = await ask(client, owner, "Is CNC 01 busy tomorrow, and why is ORD-1041 delayed?")
    kinds = [k for k, _ in evs]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert {"tool_start", "tool_result", "ui_widget", "token", "related_records", "context_update"} <= set(
        kinds
    )
    seqs = [d["sequence"] for _, d in evs]
    assert seqs == sorted(seqs) and all(d["schema_version"] == 1 for _, d in evs)
    tools = {d["tool"] for k, d in evs if k == "tool_start"}
    assert tools == {"machine_schedule", "why_delayed"}  # both parts, in one turn
    widgets = [d["widget"] for k, d in evs if k == "ui_widget"]
    assert all(w["type"] in ("section", "table", "bar_chart", "key_values") for w in widgets)
    cards = next(d["cards"] for k, d in evs if k == "context_update")
    assert {c["kind"] for c in cards} == {"machine", "order"}
    answer = "".join(d["text"] for k, d in evs if k == "token")
    assert "CNC 01" in answer and "ORD-1041" in answer

    cid = evs[0][1]["conversation_id"]
    conv = (await client.get(f"/ai/conversations/{cid}", headers=owner)).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    saved = conv["messages"][1]
    assert saved["content"].strip() == answer.strip() and saved["widgets"] and saved["context"]
    assert {t["tool"] for t in saved["tools"]} == tools and all(t["ok"] for t in saved["tools"])

    # a follow-up in the same conversation; search finds it; rename; delete
    await ask(client, owner, "Which orders are at risk of delay?", cid)
    assert len((await client.get(f"/ai/conversations/{cid}", headers=owner)).json()["messages"]) == 4
    found = (await client.get("/ai/conversations", params={"q": "at risk"}, headers=owner)).json()
    assert [c["id"] for c in found] == [cid]
    assert (
        await client.patch(f"/ai/conversations/{cid}", json={"title": "CNC 01 and delays"}, headers=owner)
    ).json()["title"] == "CNC 01 and delays"
    assert (await client.delete(f"/ai/conversations/{cid}", headers=owner)).status_code == 204
    assert (await client.get(f"/ai/conversations/{cid}", headers=owner)).status_code == 404


async def test_conversations_are_private_and_tools_follow_the_role(client: AsyncClient) -> None:
    co = await _demo_co("ai2")
    other = await _demo_co("ai2b")
    owner = await headers_for(client, co)
    evs = await ask(client, owner, "What do customers owe us?")
    cid = evs[0][1]["conversation_id"]
    # another user of the same company, and the owner of another company, can't see it
    planner = await headers_for(client, co, "planner")
    assert (await client.get(f"/ai/conversations/{cid}", headers=planner)).status_code == 404
    assert (await client.get("/ai/conversations", headers=planner)).json() == []
    stranger = await headers_for(client, other)
    assert (await client.get(f"/ai/conversations/{cid}", headers=stranger)).status_code == 404
    r = await client.post(CHAT, json={"message": "and now?", "conversation_id": cid}, headers=stranger)
    assert "Conversation not found" in r.text

    # the accountant has no Planning access: planning tools are never offered, money tools are
    acc = await headers_for(client, co, "accountant")
    st = (await client.get("/ai/status", headers=acc)).json()
    assert (
        "machine_schedule" not in st["tools"]
        and "plan_summary" not in st["tools"]
        and "receivables" in st["tools"]
    )
    evs = await ask(client, acc, "Is CNC 01 busy tomorrow?")
    assert not [d for k, d in evs if k == "tool_start"]
    assert "access" in "".join(d["text"] for k, d in evs if k == "token")
    # the planner can't see money
    evs = await ask(client, planner, "What do customers owe us?")
    assert not [d for k, d in evs if k == "tool_start"]

    # tools read only the caller's company (RLS): the other company's orders never show up
    evs = await ask(client, stranger, "Which orders are at risk of delay?")
    mine = {
        o["number"]
        for o in (await client.get("/orders", params={"limit": 100}, headers=owner)).json()["items"]
    }
    theirs = {
        o["number"]
        for o in (await client.get("/orders", params={"limit": 100}, headers=stranger)).json()["items"]
    }
    rows = [w for k, d in evs if k == "ui_widget" for w in [d["widget"]] if w["type"] == "table"]
    shown = {r["order"] for w in rows for r in w["rows"]}
    assert shown <= theirs and (not (mine - theirs) or not (shown & (mine - theirs)))


async def test_independent_tools_run_in_parallel_with_isolated_failures(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    co = await _demo_co("ai3")
    owner = await headers_for(client, co)

    async def slow(s: Any, c: Any, a: dict[str, Any]) -> ToolOut:
        await asyncio.sleep(0.6)
        return ToolOut(summary="slow tool done", data={})

    async def broken(s: Any, c: Any, a: dict[str, Any]) -> ToolOut:
        raise RuntimeError("boom")

    async def stuck(s: Any, c: Any, a: dict[str, Any]) -> ToolOut:
        await asyncio.sleep(5)
        return ToolOut(summary="never", data={})

    monkeypatch.setattr(BY_NAME["receivables"], "fn", slow)
    monkeypatch.setattr(BY_NAME["payables"], "fn", slow)
    monkeypatch.setattr(BY_NAME["orders_at_risk"], "fn", broken)
    monkeypatch.setattr(BY_NAME["purchase_orders"], "fn", stuck)
    monkeypatch.setattr(g, "TOOL_TIMEOUT", 1.0)
    t0 = time.monotonic()
    evs = await ask(client, owner, "What do customers owe us, what do we owe suppliers, which orders are at risk, "
                                   "and any open purchase orders?")  # fmt: skip
    took = time.monotonic() - t0
    res = {d["tool"]: d for k, d in evs if k == "tool_result"}
    assert set(res) == {"receivables", "payables", "orders_at_risk", "purchase_orders"}
    assert res["receivables"]["ok"] and res["payables"]["ok"]
    assert (
        not res["orders_at_risk"]["ok"] and not res["purchase_orders"]["ok"]
    )  # failure and timeout isolated
    assert took < 0.6 * 2 + 1.0 + 1.5  # the two 0.6 s tools ran side by side, the stuck one was cut at 1 s
    answer = "".join(d["text"] for k, d in evs if k == "token")
    assert answer.count("slow tool done") == 2 and evs[-1][0] == "done"


async def test_rate_limit_falls_back_to_the_smaller_model(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = OpenAICompatibleLLM("https://llm.invalid/v1", "k", "big", "small", 5)
    seen: list[str] = []

    async def post(payload: dict[str, Any]) -> httpx.Response:
        seen.append(payload["model"])
        if payload["model"] == "big":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={"model": "small", "choices": [{"message": {"content": "hi", "tool_calls": [
            {"id": "c1", "function": {"name": "plan_summary", "arguments": "{}"}}]}}], "usage": {"total_tokens": 9}})  # fmt: skip

    monkeypatch.setattr(llm, "_post", post)
    res = await llm.chat(
        [{"role": "user", "content": "x"}], tools=[{"type": "function", "function": {"name": "plan_summary"}}]
    )
    assert seen == ["big", "small"] and res.model == "small" and res.tool_calls[0].name == "plan_summary"

    async def always_429(payload: dict[str, Any]) -> httpx.Response:
        return httpx.Response(429, json={})

    monkeypatch.setattr(llm, "_post", always_429)
    llm.max_wait = 0  # don't sleep in the test
    with pytest.raises(LLMError, match="quota"):
        await llm.chat([{"role": "user", "content": "x"}])


async def test_invoice_reading_on_the_vision_model(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = OpenAICompatibleLLM("https://llm.invalid/v1", "k", "vision", "", 5)
    sent: dict[str, Any] = {}

    async def post(payload: dict[str, Any]) -> httpx.Response:
        sent.update(payload)
        return httpx.Response(
            200, json={"model": "vision", "choices": [{"message": {"content": '{"is_invoice": true}'}}]}
        )

    monkeypatch.setattr(llm, "_post", post)
    client = ai_service.VisionAIClient(llm, "vision")
    files = [ai_service.InputFile(b"\x89PNG", "image/png")] * 7
    res = await client.extract_json(
        task="invoice", system="s", instructions="read", schema={"type": "object"}, files=files
    )
    assert res.ok and res.data == {"is_invoice": True} and res.mode == "live"
    parts = sent["messages"][1]["content"]
    assert sum(p["type"] == "image_url" for p in parts) == ai_service.MAX_IMAGES  # Groq takes up to 5 images
    assert sent["response_format"] == {"type": "json_object"}
    with pytest.raises(ai_service.AIError):
        await client.extract_json(task="invoice", system="s", instructions="", schema={}, files=[])

    # with OCR text, the text model reads it (Groq's free vision model can't write a whole invoice in a minute)
    client = ai_service.VisionAIClient(llm, "vision", "text-model")
    res = await client.extract_json(task="invoice", system="s", instructions="read", schema={"type": "object"},
                                    files=[], text="p1 [0.05,0.03,0.21,0.05] TAX INVOICE")  # fmt: skip
    assert sent["model"] == "text-model" and isinstance(sent["messages"][1]["content"], str)
    assert "TAX INVOICE" in sent["messages"][1]["content"] and sent["max_tokens"] <= 6000


def test_rate_limit_wait_comes_from_the_headers() -> None:
    assert wait_seconds({"retry-after": "7"}) == 7
    assert wait_seconds({"x-ratelimit-reset-tokens": "1m2.5s"}) == 63.0
    assert wait_seconds({"x-ratelimit-reset-tokens": "577ms"}) == pytest.approx(1.077)
    assert wait_seconds({}) == 2.0


async def test_a_request_too_large_for_the_plan_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = OpenAICompatibleLLM("https://llm.invalid/v1", "k", "big", "", 5, max_wait=60, max_waits=3)
    calls: list[int] = []

    async def post(payload: dict[str, Any]) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"x-should-retry": "false", "retry-after": "1"}, json={})

    monkeypatch.setattr(llm, "_post", post)
    with pytest.raises(LLMError, match="too large"):
        await llm.chat([{"role": "user", "content": "x"}])
    assert len(calls) == 1


def test_compact_item_cells_are_accepted() -> None:
    doc = build_document(
        {"is_invoice": True, "fields": {}, "lines": [{"product_name": "M8 bolt", "quantity": 500}]}, None
    )
    assert doc["lines"][0]["product_name"]["raw"] == "M8 bolt" and doc["lines"][0]["quantity"]["raw"] == "500"
