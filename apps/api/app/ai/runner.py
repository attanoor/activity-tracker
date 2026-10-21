"""Runs one AI level: cache, call, validate, retry with the errors, then repair or fall back.

`validate(data)` returns (cleaned, errors). With no errors the result is cached and returned as "ok".
After the last attempt, `repair(last_data)` may salvage a result ("partial"), else `fallback()` builds one in
code ("fallback"). Only clean results are cached, so a later run can still do better.
"""

import hashlib
import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.ai.llm import LLM, LLMUnavailable
from app.models import AiCache

log = logging.getLogger("ai")
ATTEMPTS = 3

RULES = (
    "Rules: write plain, specific English. Use ONLY numbers, durations, times and ticket numbers that appear in "
    "the facts; never estimate, add, round or convert them. Write durations exactly as the facts do (like 1h18m "
    "or 45m), never in seconds. Never mention internal ids such as b3. Do not invent work, priorities or "
    "outcomes that are not in the facts (an email is sent or replied to, never 'resolved'). "
    "Answer with a single JSON object exactly in the requested shape, no extra keys, no commentary."
)


def cache_key(level: str, model: str, system: str, payload: dict) -> str:
    raw = json.dumps({"l": level, "m": model, "s": system, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def run(db: Session, llm: LLM | None, model: str, level: str, system: str, payload: dict, shape: str,
        validate: Callable[[dict], tuple[dict, list[str]]],
        fallback: Callable[[], dict],
        repair: Callable[[dict], dict | None] | None = None) -> tuple[dict, str]:
    if llm is None:
        return fallback(), "fallback"
    key = cache_key(level, model, system, payload)
    hit = db.get(AiCache, key)
    if hit:
        return hit.output, "ok"
    feedback, last = "", None
    for attempt in range(ATTEMPTS):
        user = (f"FACTS (JSON):\n{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                f"Reply as JSON in this shape:\n{shape}\n{feedback}")
        try:
            raw = llm(f"{system}\n\n{RULES}", user)
        except LLMUnavailable as e:
            log.warning("%s: model unavailable: %s", level, e)
            return fallback(), "fallback"
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except ValueError:
            feedback = "Your last reply was not a JSON object. Reply with JSON only."
            continue
        last = data
        cleaned, errors = validate(data)
        if not errors:
            db.merge(AiCache(key=key, level=level, output=cleaned))
            db.commit()
            return cleaned, "ok"
        log.info("%s attempt %s rejected: %s", level, attempt + 1, errors)
        feedback = "Your last reply had these problems, fix them:\n- " + "\n- ".join(errors[:12])
    if last is not None and repair:
        fixed = repair(last)
        if fixed is not None:
            return fixed, "partial"
    return fallback(), "fallback"
