"""Shared agent infrastructure: Anthropic SDK wrapper with retries,
structured output parsing, and hallucination validation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from anthropic import APIError, AsyncAnthropic, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_VOICE_MD = Path(__file__).parent / "_voice.md"
_NUMBER_REGEX = re.compile(r"-?\$?\d[\d,.]*[KMB]?", re.IGNORECASE)


def _normalize_number(s: str) -> float | None:
    """Strip currency, expand K/M/B suffixes, return float."""
    s = s.replace("$", "").replace(",", "").strip().upper()
    multiplier = 1
    if s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def validate_no_hallucinated_numbers(
    input_text: str, output_text: str, tolerance: float = 0.001
) -> bool:
    """Every digit-string in output must match a digit-string in input
    (after normalization). Returns False if any output number is novel.
    """
    input_nums: list[float] = []
    for m in _NUMBER_REGEX.findall(input_text):
        n = _normalize_number(m)
        if n is not None:
            input_nums.append(n)
    for m in _NUMBER_REGEX.findall(output_text):
        n = _normalize_number(m)
        if n is None:
            continue
        if not any(
            abs(n - i) <= tolerance * max(abs(n), abs(i), 1) for i in input_nums
        ):
            return False
    return True


def load_voice() -> str:
    return _VOICE_MD.read_text(encoding="utf-8")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((APIError, RateLimitError)),
)
async def _call_claude(
    client: AsyncAnthropic,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> str:
    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


async def run_agent(
    *,
    model: str,
    role_prompt: str,
    json_schema_description: str,
    input_payload: dict,
    fallback_factory: Callable[[dict], dict],
    client: AsyncAnthropic | None = None,
) -> dict:
    """Run a single agent. Returns {'degraded': bool, ...} dict.

    On any failure (API error, malformed JSON, hallucination) → fallback.
    """
    client = client or AsyncAnthropic()
    voice = load_voice()
    system = f"{voice}\n\n---\n\n{role_prompt}\n\n{json_schema_description}"
    user = f"Input:\n```json\n{json.dumps(input_payload, indent=2)}\n```\n\nReturn JSON only."

    try:
        text = await _call_claude(
            client, model=model, system=system, user=user
        )
        parsed = _extract_json(text)
        if parsed is None:
            # Retry once with stricter instruction
            text = await _call_claude(
                client,
                model=model,
                system=system,
                user=user
                + "\n\nIMPORTANT: respond with JSON ONLY, no prose.",
            )
            parsed = _extract_json(text)
        if parsed is None:
            raise ValueError("Agent returned no parseable JSON")

        if not validate_no_hallucinated_numbers(
            json.dumps(input_payload), json.dumps(parsed)
        ):
            raise ValueError("Hallucinated number detected in agent output")

        return {"degraded": False, **parsed}
    except Exception as e:
        return {"degraded": True, "reason": str(e), **fallback_factory(input_payload)}


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of text. Tolerates leading/trailing prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
