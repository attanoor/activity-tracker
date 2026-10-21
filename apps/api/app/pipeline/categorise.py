"""Deterministic rule categoriser. Runs before any AI; the AI only suggests new rules for an admin to accept."""

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

# Session kinds that are not activity get a fixed class and no category.
KIND_KLASS = {"idle": "idle", "locked": "away", "private": "private", "paused": "paused"}
UNCATEGORISED = "neutral"


@dataclass(frozen=True)
class Rule:
    id: int
    field: str  # domain | app | title
    pattern: str
    category_id: int
    klass: str
    priority: int = 0


def _domain_matches(pattern: str, domain: str) -> bool:
    pattern = pattern.lower()
    if any(c in pattern for c in "*?["):
        return fnmatchcase(domain, pattern)
    return domain == pattern or domain.endswith("." + pattern)


def rule_matches(rule: Rule, app: str | None, domain: str | None, title: str | None) -> bool:
    if rule.field == "domain":
        return bool(domain) and _domain_matches(rule.pattern, domain.lower())
    if rule.field == "app":
        return bool(app) and fnmatchcase(app.lower(), rule.pattern.lower())
    if rule.field == "title":
        try:
            return bool(title) and re.search(rule.pattern, title, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def order_rules(rules: list[Rule]) -> list[Rule]:
    # Higher priority first; at equal priority, a domain rule beats a title rule beats an app rule
    # (a browser process says less than the site it shows).
    specificity = {"domain": 0, "title": 1, "app": 2}
    return sorted(rules, key=lambda r: (-r.priority, specificity.get(r.field, 9), r.id))


def categorise(kind: str, app: str | None, domain: str | None, title: str | None,
               ordered_rules: list[Rule]) -> tuple[int | None, str]:
    """Returns (category_id, klass). `ordered_rules` must come from `order_rules`."""
    if kind != "active":
        return None, KIND_KLASS.get(kind, "away")
    for rule in ordered_rules:
        if rule_matches(rule, app, domain, title):
            return rule.category_id, rule.klass
    return None, UNCATEGORISED
