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
    ) -> AIResult: ...


MAX_IMAGES = 5  # Groq vision models accept up to 5 images per request


def _image_part(f: InputFile) -> dict[str, Any]:
    data = base64.standard_b64encode(f.data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{f.media_type};base64,{data}"}}


class VisionAIClient:
    """Reads page images with a vision model and returns JSON (JSON mode + the schema in the prompt)."""

    mode: Literal["live", "mock", "template"] = "live"

    def __init__(self, llm: OpenAICompatibleLLM, model: str) -> None:
        self._llm = llm
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
        images = [f for f in files if f.media_type != "application/pdf"][:MAX_IMAGES]
        if not images:
            raise AIError("Nothing readable to send to the AI (no page images).")
        prompt = (f"{instructions}\n\nReply with one JSON object only, matching this JSON schema "
                  f"(no prose, no code fences):\n{json.dumps(schema, separators=(',', ':'))}")  # fmt: skip
        messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                    {"role": "user", "content": [*(_image_part(f) for f in images), {"type": "text", "text": prompt}]}]  # fmt: skip
        try:
            res = await self._llm.chat(messages, json_mode=True, model=self.model, max_tokens=8000)
        except LLMError as exc:
            raise AIError(str(exc)) from exc
        try:
            data = json.loads(res.content)
        except json.JSONDecodeError as exc:
            raise AIError("AI returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise AIError("AI returned invalid JSON")
        return AIResult(data, res.content, res.model or self.model, "live", "stop", res.usage)


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
    if s.llm_api_key and s.llm_api_key.get_secret_value():
        llm = OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key.get_secret_value(), s.llm_vision_model, "",
                                  s.llm_timeout_seconds * 2)  # fmt: skip
        return VisionAIClient(llm, s.llm_vision_model)
    return MockAIClient()
