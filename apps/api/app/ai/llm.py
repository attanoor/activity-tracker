"""The local model, behind one callable so tests can swap in a fake: (system, user) -> raw JSON text."""

from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session

from app import settings_store

LLM = Callable[[str, str], str]


class LLMUnavailable(Exception):
    pass


# Tests set this to a fake; production leaves it None and uses Ollama from the AI settings.
override: LLM | None = None


def ollama(url: str, model: str, timeout_s: float = 300) -> LLM:
    def call(system: str, user: str) -> str:
        try:
            r = httpx.post(f"{url.rstrip('/')}/api/chat", timeout=timeout_s, json={
                "model": model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0.2, "num_ctx": 8192}})
            r.raise_for_status()
            return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMUnavailable(str(e)) from e
    return call


def get_llm(db: Session) -> tuple[LLM | None, str]:
    """(callable or None if AI is switched off, model name)."""
    if override:
        return override, "test-model"
    cfg = settings_store.get(db, "ai")
    if not cfg["enabled"]:
        return None, "off"
    return ollama(cfg["ollama_url"], cfg["model"], cfg["timeout_s"]), cfg["model"]
