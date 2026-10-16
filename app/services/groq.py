"""Thin client for Groq's OpenAI-compatible API. Base URL and model names come from settings."""

from typing import Any

import httpx

from app.config import get_settings


class AIError(Exception):
    """The AI call couldn't be made or didn't return usable output."""


async def chat_completion(
    prompt: str,
    *,
    model: str | None,
    max_tokens: int,
    timeout_seconds: float,
    system: str | None = None,
    **options: Any,
) -> str:
    """Send one user message (plus an optional system message) and return the reply text."""
    settings = get_settings()
    if not settings.groq_api_key:
        raise AIError("GROQ_API_KEY is not set.")
    if not model:
        raise AIError("No model configured for this call (see the GROQ_* settings).")

    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={"model": model, "max_tokens": max_tokens, "messages": messages, **options},
            )
    except httpx.HTTPError as exc:
        raise AIError(f"Couldn't reach Groq: {exc!r}") from exc

    if response.is_error:
        raise AIError(f"Groq returned {response.status_code}: {response.text[:500]}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError(f"Unexpected response from Groq: {response.text[:500]}") from exc
    if not content or not content.strip():
        raise AIError("Groq returned an empty reply.")
    return content.strip()
