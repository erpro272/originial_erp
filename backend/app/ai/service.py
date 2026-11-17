"""Document extraction (invoices) with a real client (a vision model on the OpenAI-compatible endpoint, Groq's
free Llama 4 Scout by default) and a mock client.

The mock is used automatically when ``LLM_API_KEY`` is not set, so the app and the tests run without a key.
It returns fixture JSON from ``app/ai/fixtures/<task>/``. The assistant's chat client is ``app.ai.llm``.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

from app.ai.llm import LLMError, OpenAICompatibleLLM
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
        text: str | None = None,
    ) -> AIResult: ...


MAX_IMAGES = 5  # Groq vision models accept up to 5 images per request


def _image_part(f: InputFile) -> dict[str, Any]:
    data = base64.standard_b64encode(f.data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{f.media_type};base64,{data}"}}


class VisionAIClient:
    """Returns JSON (JSON mode + the schema in the prompt). With OCR `text` (lines with page + box) the text model
    reads it: Groq's free vision model may only write ~1,000 tokens a minute, too few for an invoice. Without text,
    the vision model reads the page images."""

    mode: Literal["live", "mock", "template"] = "live"

    def __init__(self, llm: OpenAICompatibleLLM, model: str, text_model: str = "") -> None:
        self._llm = llm
        self.model = model
        self.text_model = text_model

    async def extract_json(
        self,
        *,
        task: str,
        system: str,
        instructions: str,
        schema: dict[str, Any],
        files: list[InputFile],
        fixture_hint: str | None = None,
        text: str | None = None,
    ) -> AIResult:
        if text and self.text_model:
            # the instructions describe the output (`text_format`); the long JSON schema would cost ~2k tokens
            prompt = (f"{instructions}\n\nThe document's text, read by OCR, one line each as `p<page> [x0,y0,x1,y1] text` "
                      "(box = fractions of the page). OCR may misread characters: fix obvious slips.\n"
                      f"<ocr>\n{text[:14000]}\n</ocr>\n\nReply with one compact JSON object only (no spaces or newlines).")  # fmt: skip
            ask: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            # free tier: input + max_tokens must fit the 8k tokens-a-minute budget (~2.7 characters a token here)
            room = 7700 - int((len(prompt) + len(system)) / 2.7)
            return await self._ask(ask, self.text_model, max(2000, min(6000, room)))
        images = [f for f in files if f.media_type != "application/pdf"][:MAX_IMAGES]
        if not images:
            raise AIError("Nothing readable to send to the AI (no page images).")
        prompt = (f"{instructions}\n\nReply with one JSON object only, matching this JSON schema "
                  f"(no prose, no code fences):\n{json.dumps(schema, separators=(',', ':'))}")  # fmt: skip
        messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                    {"role": "user", "content": [*(_image_part(f) for f in images), {"type": "text", "text": prompt}]}]  # fmt: skip
        return await self._ask(messages, self.model, 6000)

    async def _ask(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> AIResult:
        try:
            res = await self._llm.chat(messages, json_mode=True, model=model, max_tokens=max_tokens)
        except LLMError as exc:
            raise AIError(str(exc)) from exc
        try:
            data = json.loads(res.content)
        except json.JSONDecodeError as exc:
            raise AIError("AI returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise AIError("AI returned invalid JSON")
        return AIResult(data, res.content, res.model or model, "live", "stop", res.usage)


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
        text: str | None = None,
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
    if s.llm_api_key and s.llm_api_key.get_secret_value():
        llm = OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key.get_secret_value(), s.llm_vision_model, "",
                                  s.llm_timeout_seconds * 2, max_wait=65, max_waits=3)  # background job: wait out the minute  # fmt: skip
        return VisionAIClient(llm, s.llm_vision_model, s.llm_primary_model)
    return MockAIClient()
