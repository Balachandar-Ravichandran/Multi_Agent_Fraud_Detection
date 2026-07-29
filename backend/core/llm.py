"""Shared Anthropic client + a thin per-stage call helper.

Not executed in this pass -- no live API call has been made against this
module yet. Wire up and smoke-test with a real ANTHROPIC_API_KEY (expected
in backend/.env, never read directly by this codebase) before trusting it
end to end.

"Effort" is the PRD's own informal term (Sections 5, 6, 8, 9, 10) for how
much a stage should think; mapped here to max_tokens since that's the
concrete lever the Messages API exposes.
"""
from __future__ import annotations

import os
from functools import lru_cache

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-5"

EFFORT_MAX_TOKENS = {"low": 512, "medium": 1024, "high": 2048}


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (expected in backend/.env)")
    return Anthropic(api_key=api_key)


def call(model: str, effort: str, system: str, user_message: str, max_tokens: int | None = None) -> str:
    """One non-streaming Messages API call. Returns the concatenated text content."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens or EFFORT_MAX_TOKENS[effort],
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
