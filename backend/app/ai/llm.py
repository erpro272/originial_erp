"""OpenAI-compatible chat client (Groq's free tier by default) with a rate-limit fallback model.

Only this module talks to the LLM provider. Without ``LLM_API_KEY`` the scripted mock in ``mock.py`` is used
(the app, the tests and the e2e suite run offline). The key is never logged.
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model call failed (network, API error, invalid output). Safe to retry."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLM(Protocol):
    mode: Literal["live", "mock"]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        model: str | None = None,
        max_tokens: int = 1024,
        on_wait: Callable[[float], None] | None = None,  # told before waiting out a rate limit
    ) -> ChatResult: ...


def _parse(body: dict[str, Any]) -> ChatResult:
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=c.get("id") or fn.get("name", "call"), name=fn.get("name", ""),
                              args=args if isinstance(args, dict) else {}))  # fmt: skip
    usage = {k: int(v) for k, v in (body.get("usage") or {}).items() if isinstance(v, int)}
    return ChatResult(
        content=msg.get("content") or "", tool_calls=calls, model=body.get("model", ""), usage=usage
    )


def wait_seconds(headers: Any) -> float:
    """How long a 429 asks us to wait: `retry-after`, else `x-ratelimit-reset-tokens` ("51.8s", "1m2.5s", "577ms")."""
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        pass
    total, text = 0.0, str(headers.get("x-ratelimit-reset-tokens") or "")
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", text):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total + 0.5 if total else 2.0


class OpenAICompatibleLLM:
    """POST {base}/chat/completions. 429 (free-tier rate limit) -> one retry on the fallback model."""

    mode: Literal["live", "mock"] = "live"

    def __init__(self, base_url: str, api_key: str, primary: str, fallback: str, timeout: float,
                 max_wait: float = 20.0, max_waits: int = 1, reasoning: str = "low", prefer_wait: float = 0) -> None:  # fmt: skip
        self.reasoning = reasoning
        self.prefer_wait = prefer_wait
        # rate limits: longest single wait, and how many waits (chat: one short one; background jobs: a few)
        self.max_wait, self.max_waits = max_wait, max_waits
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self.primary, self.fallback = primary, fallback
        self.timeout = timeout

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(f"{self.base_url}/chat/completions", json=payload,
                                     headers={"Authorization": f"Bearer {self._key}"})  # fmt: skip

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        model: str | None = None,
        max_tokens: int = 1400,  # Groq reserves max_tokens against the minute's budget: keep it near real use
        on_wait: Callable[[float], None] | None = None,  # told before waiting out a rate limit
    ) -> ChatResult:
        payload: dict[str, Any] = {"model": model or self.primary, "messages": messages,
                                   "max_tokens": max_tokens, "temperature": 0.2}  # fmt: skip
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        models = [payload["model"]] + (
            [self.fallback] if self.fallback and self.fallback != payload["model"] else []
        )
        # free tier: tokens per minute are limited. On a 429 wait what the API asks (if short), retry, then try the
        # fallback model (its own quota), before giving up.
        # On a 429: switch to the fallback model at once (its own quota); when every model is limited, wait what the
        # API asks (if within max_wait) and go round again. 5xx: one short retry.
        last, waits, i, retried = "", 0, 0, False
        tried: set[str] = set()
        while i < 12:
            m = models[i % len(models)]
            i += 1
            tried.add(m)
            payload["model"] = m
            if (
                "gpt-oss" in m
            ):  # reasoning models: how hard to think (assistant: medium; bulk extraction: low)
                payload["reasoning_effort"] = self.reasoning
            else:
                payload.pop("reasoning_effort", None)
            try:
                r = await self._post(payload)
            except httpx.HTTPError as exc:
                raise LLMError("Could not reach the AI service") from exc
            if r.status_code == 200:
                res = _parse(r.json())
                log.info("LLM %s used %s", m, {k: v for k, v in res.usage.items() if k.endswith("tokens")})
                return res
            last = f"AI API error {r.status_code}"
            if r.status_code == 429:
                if (
                    r.headers.get("x-should-retry") == "false"
                ):  # e.g. the request alone is over the free tier's limit
                    last = "too large"
                short = wait_seconds(r.headers)
                if (
                    m == models[0]
                    and short <= self.prefer_wait
                    and waits < self.max_waits
                    and last != "too large"
                ):
                    waits += 1  # a short wait for the main model beats a weaker answer from the fallback
                    log.warning("LLM rate limited on %s, waiting %.0fs for it", m, short)
                    if on_wait:
                        on_wait(short)
                    await asyncio.sleep(short)
                    i -= 1
                    continue
                if len(tried) < len(models):
                    log.warning("LLM rate limited on %s, trying %s", m, models[i % len(models)])
                    continue
                after = max(wait_seconds(r.headers), 15.0 * waits)  # the bucket refills gradually: back off
                if waits >= self.max_waits or after > self.max_wait or last == "too large":
                    break
                waits += 1
                log.warning("LLM rate limited on every model, retrying in %.0fs", after)
                if on_wait:
                    on_wait(after)
                await asyncio.sleep(after)
                i = 0
                continue
            if r.status_code >= 500 and not retried:
                retried = True
                await asyncio.sleep(0.5)
                i -= 1
                continue
            break
        if last == "too large":
            raise LLMError("This request is too large for the AI plan's per-minute limit.")
        if last.endswith("429"):
            raise LLMError("The free AI quota is used up for this minute. Try again shortly.")
        raise LLMError(last)


def get_llm() -> LLM:
    s = get_settings()
    if s.llm_api_key and s.llm_api_key.get_secret_value():
        return OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key.get_secret_value(), s.llm_primary_model,
                                   s.llm_fallback_model, s.llm_timeout_seconds, max_wait=35, max_waits=2, reasoning="medium",
                                   prefer_wait=15)  # fmt: skip
    from app.ai.mock import ScriptedLLM

    return ScriptedLLM()
