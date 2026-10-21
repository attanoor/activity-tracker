"""Checks on what the model writes. Code computed every number; the model may only repeat them.

- Number check: every number in the text must be derivable from the facts the model was given (the value
  itself, or the same duration in minutes / hours / h-m form, or a number inside a fact string such as a time).
- Reference check: every ticket reference (#123) must be a ticket in that day's data.
"""

import re

NUM = re.compile(r"\d+(?:\.\d+)?")
TICKET_REF = re.compile(r"#\s?0*(\d{1,8})\b")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
ALWAYS = {"0", "1"}


def _norm(token: str) -> str:
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def _add_number(out: set, v: float) -> None:
    out.add(_norm(str(int(v)) if float(v).is_integer() else str(round(v, 1))))
    out.add(_norm(str(round(v))))


def _walk(obj, out: set) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        _add_number(out, v)
        if v >= 60:  # may be a duration in seconds: allow it in minutes, hours and h+m forms
            minutes = v / 60
            _add_number(out, minutes)
            h, m = divmod(round(minutes), 60)
            out.update({_norm(str(h)), _norm(str(m))})
            _add_number(out, round(minutes / 60, 1))
        return
    if isinstance(obj, str):
        for t in NUM.findall(obj.replace(",", "")):
            out.add(_norm(t))
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk(k, out)
            _walk(v, out)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _walk(v, out)


def allowed_numbers(*facts) -> set[str]:
    out = set(ALWAYS)
    for f in facts:
        _walk(f, out)
    return out


def refs_in(*facts) -> set[str]:
    """#numbers already present in the facts (e.g. 'Pull request #318' in a page title) may be repeated."""
    found: set[str] = set()

    def walk(o):
        if isinstance(o, str):
            found.update(m.lstrip("0") for m in TICKET_REF.findall(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    for f in facts:
        walk(f)
    return found


# Recommendation sizes a coach may suggest ("a 10-minute break", "every 30 minutes"); allowed in advice only.
ADVICE_NUMBERS = {"2", "3", "5", "10", "15", "20", "25", "30", "45", "60", "90"}


def bad_numbers(text: str, allowed: set[str]) -> list[str]:
    return [t for t in NUM.findall((text or "").replace(",", "")) if _norm(t) not in allowed]


def bad_refs(text: str, tickets: set[str]) -> list[str]:
    return [m for m in TICKET_REF.findall(text or "") if m.lstrip("0") not in tickets]


def problems(text: str, allowed: set[str], tickets: set[str]) -> list[str]:
    out = []
    if nums := bad_numbers(text, allowed):
        out.append(f"numbers not in the facts: {', '.join(sorted(set(nums)))}")
    if refs := bad_refs(text, tickets):
        out.append(f"tickets not in the facts: {', '.join('#' + r for r in sorted(set(refs)))}")
    return out


def scrub(text: str, allowed: set[str], tickets: set[str]) -> str:
    """Drops each sentence that still breaks a rule after retries."""
    keep = [s for s in SENTENCE.split(text or "") if not problems(s, allowed, tickets)]
    return " ".join(keep).strip()
