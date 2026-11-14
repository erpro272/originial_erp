"""AI service with a real (Anthropic) client and a mock client.

The mock is used automatically when ``ANTHROPIC_API_KEY`` is not set, so the app and
the tests run without a key. It returns fixture JSON from ``app/ai/fixtures/<task>/``.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

import anthropic

from app.core.config import get_settings

log = logging.getLogger(__name__)
FIXTURES = Path(__file__).parent / "fixtures"

MediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]


@dataclass(frozen=True)
class InputFile:
    data: bytes
    media_type: MediaType


@dataclass
class AIResult:
    data: dict[str, Any] | None  # parsed JSON, or None if the model refused
    raw_text: str
    model: str
    mode: Literal["live", "mock", "template"]
    stop_reason: str | None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.data is not None


class AIError(Exception):
    """The AI call failed (network, API error, invalid output). Safe to retry."""


class AIClient(Protocol):
    mode: Literal["live", "mock", "template"]

    async def extract_json(
        self,
        *,
        task: str,
        system: str,
        instructions: str,
        schema: dict[str, Any],
        files: list[InputFile],
        fixture_hint: str | None = None,
    ) -> AIResult: ...


def _content_block(f: InputFile) -> dict[str, Any]:
    data = base64.standard_b64encode(f.data).decode()
    if f.media_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": f.media_type, "data": data},
        }
    return {"type": "image", "source": {"type": "base64", "media_type": f.media_type, "data": data}}


class AnthropicAIClient:
    mode: Literal["live", "mock", "template"] = "live"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)
        self.model = model

    async def extract_json(
        self,
        *,
        task: str,
        system: str,
        instructions: str,
        schema: dict[str, Any],
        files: list[InputFile],
        fixture_hint: str | None = None,
    ) -> AIResult:
        content: list[dict[str, Any]] = [
            *(_content_block(f) for f in files),
            {"type": "text", "text": instructions},
        ]
        messages: Any = [{"role": "user", "content": content}]
        try:
            # Streaming avoids HTTP timeouts on large multi-page documents.
            async with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=system,
                messages=messages,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                # On a policy decline, the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                msg = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise AIError("AI rate limit reached, retry later") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"AI API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("Could not reach the AI service") from exc

        text = "".join(b.text for b in msg.content if b.type == "text")
        usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
        if msg.stop_reason == "refusal":
            log.warning("AI task %s refused", task)
            return AIResult(None, text, msg.model, "live", msg.stop_reason, usage)
        if msg.stop_reason == "max_tokens":
            raise AIError("AI output was cut off (document too long)")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError("AI returned invalid JSON") from exc
        return AIResult(data, text, msg.model, "live", msg.stop_reason, usage)


class MockAIClient:
    """Returns ``fixtures/<task>/<fixture_hint>.json`` (or ``default.json``)."""

    mode: Literal["live", "mock", "template"] = "mock"

    def __init__(self, fixtures_dir: Path = FIXTURES) -> None:
        self.fixtures_dir = fixtures_dir

    async def extract_json(
        self,
        *,
        task: str,
        system: str,
        instructions: str,
        schema: dict[str, Any],
        files: list[InputFile],
        fixture_hint: str | None = None,
    ) -> AIResult:
        folder = self.fixtures_dir / task
        candidates = [folder / f"{fixture_hint}.json"] if fixture_hint else []
        candidates.append(folder / "default.json")
        for path in candidates:
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                return AIResult(json.loads(text), text, "mock", "mock", "end_turn")
        raise AIError(f"No mock fixture for task {task!r} (hint {fixture_hint!r})")


@lru_cache
def get_ai_client() -> AIClient:
    s = get_settings()
    if s.anthropic_api_key and s.anthropic_api_key.get_secret_value():
        return AnthropicAIClient(s.anthropic_api_key.get_secret_value(), s.ai_extraction_model)
    return MockAIClient()
