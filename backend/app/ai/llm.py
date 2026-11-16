"""OpenAI-compatible chat client (Groq's free tier by default) with a rate-limit fallback model.

Only this module talks to the LLM provider. Without ``LLM_API_KEY`` the scripted mock in ``mock.py`` is used
(the app, the tests and the e2e suite run offline). The key is never logged.
"""

import asyncio
import json
import logging
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


class OpenAICompatibleLLM:
    """POST {base}/chat/completions. 429 (free-tier rate limit) -> one retry on the fallback model."""

    mode: Literal["live", "mock"] = "live"

    def __init__(self, base_url: str, api_key: str, primary: str, fallback: str, timeout: float) -> None:
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
        max_tokens: int = 1024,
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
        last = ""
        for i, m in enumerate(models):
            payload["model"] = m
            try:
                r = await self._post(payload)
            except httpx.HTTPError as exc:
                raise LLMError("Could not reach the AI service") from exc
            if r.status_code == 200:
                return _parse(r.json())
            last = f"AI API error {r.status_code}"
            if r.status_code == 429 and i + 1 < len(models):
                log.warning("LLM rate limited on %s, falling back to %s", m, models[i + 1])
                continue
            if r.status_code >= 500 and i == 0:
                await asyncio.sleep(0.5)
                continue
            if r.status_code == 429:
                raise LLMError("The free AI quota is used up for this minute. Try again shortly.")
            break
        raise LLMError(last)


def get_llm() -> LLM:
    s = get_settings()
    if s.llm_api_key and s.llm_api_key.get_secret_value():
        return OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key.get_secret_value(), s.llm_primary_model,
                                   s.llm_fallback_model, s.llm_timeout_seconds)  # fmt: skip
    from app.ai.mock import ScriptedLLM

    return ScriptedLLM()
