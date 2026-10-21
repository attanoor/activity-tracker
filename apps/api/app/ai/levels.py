"""The AI levels: item -> section -> day report -> suggestions -> team day -> week/month.

Every level gets facts computed by code and returns text only. Each has a validator (shape, number check,
ticket check) and a fallback written by code, so a report is always produced even with the model down.
"""

from app.ai import guards, runner
from app.analysis.engine import fmt_hm

STATUSES = ("done", "in_progress", "blocked")
SMALL_LEFTOVER_S = 20 * 60
METRICS = ("productive", "meeting", "communication", "non_work", "idle", "deep_focus", "switches_per_hour",
           "meeting_load", "long_low_value", "communication_checks", "overtime", "top_targets")


def _text_validator(allowed: set[str], tickets: set[str], str_fields: dict[str, int], list_fields: dict[str, int] = {}):
    """Fields must be present, of the right type, within length, and pass the number and ticket checks."""
    def validate(data: dict) -> tuple[dict, list[str]]:
        out, errors = {}, []
        for f, max_len in str_fields.items():
            v = data.get(f)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"'{f}' must be a non-empty string")
                continue
            v = v.strip()[:max_len]
            errors += [f"'{f}': {p}" for p in guards.problems(v, allowed, tickets)]
            out[f] = v
        for f, max_items in list_fields.items():
            v = data.get(f, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errors.append(f"'{f}' must be a list of strings")
                continue
            items = [x.strip() for x in v if x.strip()][:max_items]
            for x in items:
                errors += [f"'{f}': {p}" for p in guards.problems(x, allowed, tickets)]
            out[f] = items
        return out, errors
    return validate


def _scrubbing_repair(allowed, tickets, str_fields, list_fields={}, fallback=None):
    def repair(data: dict) -> dict | None:
        out = {}
        for f in str_fields:
            v = guards.scrub(str(data.get(f) or ""), allowed, tickets)
            if not v:
                return None
            out[f] = v
        for f in list_fields:
            out[f] = [x for x in (guards.scrub(str(i), allowed, tickets) for i in data.get(f, []) or []) if x]
        return out
    return repair


# --- item -----------------------------------------------------------------------------------------------
ITEM_SYSTEM = ("You summarise one piece of a person's work day for their daily status report. "
               "Write one sentence (max 25 words) saying what was done on it, past tense, no filler. "
               "Start with the ticket number or name when there is one.")


def item_fallback(item: dict) -> str:
    k = item["kind"]
    if k == "ticket":
        acts = ", ".join(f"{a['action']}" for a in item.get("actions", [])) or "worked on it"
        return f"#{item['id']} {item['title']}: {acts}" + (f" ({item['time']})" if item.get("time") else "") + "."
    if k == "email_thread":
        return f"Email \"{item['subject']}\": {item['sent']} sent ({item['replies']} replies)."
    if k == "doc":
        return f"{item['title']}: {', '.join(item.get('actions', [])) or 'opened'}" + (f" ({item['time']})" if item.get("time") else "") + "."
    if k == "meeting":
        return f"Meeting \"{item['title']}\" ({item['duration']}, {item['attendees']} people)."
    return f"{item['label']}: {item['time']}."


def llm_view(item: dict) -> dict:
    """What the model sees of an item: internal ids only for tickets, where the number is meaningful."""
    return item if item["kind"] == "ticket" else {k: v for k, v in item.items() if k != "id"}


def summarise_item(db, llm, model, item: dict, tickets: set[str]) -> tuple[str, str]:
    view = llm_view(item)
    allowed = guards.allowed_numbers(view)
    tickets = tickets | guards.refs_in(view)
    out, status = runner.run(
        db, llm, model, "item", ITEM_SYSTEM, view, '{"summary": "..."}',
        _text_validator(allowed, tickets, {"summary": 300}),
        lambda: {"summary": item_fallback(item)},
        _scrubbing_repair(allowed, tickets, ["summary"]))
    return out["summary"], status


# --- section --------------------------------------------------------------------------------------------
SECTION_SYSTEM = ("You write one short section of a daily status report from item summaries. "
                  "Two or three sentences: what was achieved, grouped sensibly, most important first.")
SECTION_TITLES = {"tickets": "Tickets", "email": "Email", "docs": "Documents", "meetings": "Meetings",
                  "focus": "Focused work"}


def summarise_section(db, llm, model, name: str, items: list[str], counts: dict, tickets: set[str]) -> tuple[str, str]:
    if not items:
        return "", "skip"
    payload = {"section": SECTION_TITLES[name], "counts": counts, "items": items}
    allowed = guards.allowed_numbers(payload)
    tickets = tickets | guards.refs_in(payload)
    out, status = runner.run(
        db, llm, model, "section", SECTION_SYSTEM, payload, '{"summary": "..."}',
        _text_validator(allowed, tickets, {"summary": 700}),
        lambda: {"summary": join_sentences(items)},
        _scrubbing_repair(allowed, tickets, ["summary"]))
    return out["summary"], status


def join_sentences(items: list[str], limit: int = 5) -> str:
    parts = [i.strip().rstrip(".") + "." for i in items[:limit] if i.strip()]
    more = len(items) - limit
    return " ".join(parts) + (f" And {more} more." if more > 0 else "")


# --- day report -----------------------------------------------------------------------------------------
DAY_SYSTEM = (
    "You write a person's Daily Status Report (DSR) from their tracked day. The BLOCKS are their productive work "
    "(email, chat, meetings and admin are reported separately, but you may use the sections for context). Group "
    "the BLOCKS into a few meaningful TASKS (usually 2-6). Every block id must be used in exactly one task. Name "
    "tasks after the ticket, document, project or repository they concern. Each task summary says what was done "
    "(from the titles, ticket actions and sections) in one or two sentences, without repeating the task's time, "
    "which is shown separately. Status is done, in_progress or blocked. "
    "Highlights: the 2-4 most notable results. Blockers: only real ones visible in the facts (else empty). "
    "Tomorrow: 1-3 likely next steps from unfinished work. Insights: 2-3 sentences on how the day went, using "
    "the analysis numbers. Small blocks of the same kind (chat, search, meetings) belong in the task they "
    "supported or in one shared task; before answering, check that every id in all_block_ids appears exactly once.")
DAY_SHAPE = ('{"tasks": [{"title": "...", "block_ids": ["b1"], "summary": "...", "status": "done|in_progress|blocked"}], '
             '"highlights": ["..."], "blockers": ["..."], "tomorrow": ["..."], "insights": "..."}')


def _day_validator(blocks: list[dict], allowed: set[str], tickets: set[str]):
    ids = {b["id"] for b in blocks}

    def validate(data: dict) -> tuple[dict, list[str]]:
        errors, tasks, used = [], [], {}
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return {}, ["'tasks' must be a non-empty list"]
        for i, t in enumerate(raw_tasks):
            if not isinstance(t, dict):
                errors.append(f"task {i + 1} is not an object")
                continue
            title, summary = str(t.get("title") or "").strip(), str(t.get("summary") or "").strip()
            status = t.get("status") if t.get("status") in STATUSES else None
            bids = [b for b in t.get("block_ids") or [] if isinstance(b, str)]
            if not title:
                errors.append(f"task {i + 1} has no title")
            if status is None:
                errors.append(f"task '{title}': status must be one of {STATUSES}")
            for b in bids:
                if b not in ids:
                    errors.append(f"task '{title}': unknown block id {b}")
                elif b in used:
                    errors.append(f"block {b} is in two tasks ('{used[b]}' and '{title}')")
                else:
                    used[b] = title
            for field in (title, summary):
                errors += [f"task '{title}': {p}" for p in guards.problems(field, allowed, tickets)]
            tasks.append({"title": title[:160], "summary": summary[:600], "status": status or "in_progress",
                          "block_ids": [b for b in bids if b in ids]})
        missing = sorted(ids - set(used), key=lambda x: int(x[1:]))
        if missing:
            errors.append(f"these block ids are in no task: {', '.join(missing)}")
        lists = {}
        for f, n in (("highlights", 4), ("blockers", 4), ("tomorrow", 3)):
            v = data.get(f, [])
            if not isinstance(v, list):
                errors.append(f"'{f}' must be a list")
                v = []
            lists[f] = [str(x).strip() for x in v if str(x).strip()][:n]
            for x in lists[f]:
                errors += [f"'{f}': {p}" for p in guards.problems(x, allowed, tickets)]
        insights = str(data.get("insights") or "").strip()
        errors += [f"'insights': {p}" for p in guards.problems(insights, allowed, tickets)]
        return {"tasks": tasks, **lists, "insights": insights[:900]}, errors

    return validate


def _repair_day(blocks, allowed, tickets):
    by_id = {b["id"]: b for b in blocks}

    def repair(data: dict) -> dict | None:
        cleaned, _ = _day_validator(blocks, allowed, tickets)(data)
        if not cleaned.get("tasks"):
            return None
        seen = set()
        for t in cleaned["tasks"]:
            t["block_ids"] = [b for b in t["block_ids"] if not (b in seen or seen.add(b))]
            t["title"] = guards.scrub(t["title"], allowed, tickets) or "Work"
            t["summary"] = guards.scrub(t["summary"], allowed, tickets)
        cleaned["tasks"] = [t for t in cleaned["tasks"] if t["block_ids"]]
        cat_task = {}
        for t in cleaned["tasks"]:
            for b in t["block_ids"]:
                cat_task.setdefault(by_id[b]["category"], t)
        groups: dict = {}
        for bid in sorted(set(by_id) - seen, key=lambda x: int(x[1:])):
            b = by_id[bid]
            if b["category"] in cat_task:
                cat_task[b["category"]]["block_ids"].append(bid)  # same kind of work as an existing task
            else:
                groups.setdefault(b["category"], []).append(b)
        def task_secs(t):
            return sum(by_id[b]["seconds"] for b in t["block_ids"])
        for cat, bl in groups.items():
            if cleaned["tasks"] and sum(b["seconds"] for b in bl) < SMALL_LEFTOVER_S:
                # A few minutes of supporting work (a Stack Overflow look-up) belongs to the day's main task.
                max(cleaned["tasks"], key=task_secs)["block_ids"].extend(b["id"] for b in bl)
            else:
                cleaned["tasks"].append(category_task(cat, bl))
        for f in ("highlights", "blockers", "tomorrow"):
            cleaned[f] = [x for x in (guards.scrub(i, allowed, tickets) for i in cleaned[f]) if x]
        cleaned["insights"] = guards.scrub(cleaned["insights"], allowed, tickets)
        return cleaned
    return repair


def category_task(category: str | None, blocks: list[dict]) -> dict:
    if len(blocks) == 1:
        return fallback_task(blocks[0])
    names = ", ".join(b["label"] for b in sorted(blocks, key=lambda b: -b["seconds"])[:3])
    total = sum(b["seconds"] for b in blocks)
    return {"title": category or "Other work", "summary": f"{fmt_hm(total)} across {names}.",
            "status": "in_progress", "block_ids": [b["id"] for b in blocks]}


def fallback_task(b: dict) -> dict:
    titles = "; ".join(b["titles"][:2])
    label = f"#{b['ticket_id']} {b['label']}" if b.get("ticket_id") else b["label"]
    return {"title": label[:160], "summary": f"{fmt_hm(b['seconds'])} on {label}" + (f" ({titles})" if titles else "") + ".",
            "status": "in_progress", "block_ids": [b["id"]]}


def fallback_insights(a: dict) -> str:
    bd, focus, load = a["breakdown"], a["focus"], a["meeting_load"]
    parts = [f"Of the {fmt_hm(a['shift']['seconds'])} shift, {fmt_hm(bd['productive'])} was productive work, "
             f"{fmt_hm(bd['meeting'])} meetings and {fmt_hm(bd['communication'])} email and chat."]
    if focus["longest"]:
        parts.append(f"The longest focus block was {fmt_hm(focus['longest']['seconds'])} ({focus['longest']['main']}).")
    if load["back_to_back"]:
        parts.append(f"{load['back_to_back']} meetings ran back to back.")
    return " ".join(parts)


def write_dsr(db, llm, model, payload: dict, blocks: list[dict], analysis: dict, tickets: set[str]) -> tuple[dict, str]:
    allowed = guards.allowed_numbers(payload)
    tickets = tickets | guards.refs_in(payload)

    def fallback() -> dict:
        return {"tasks": [fallback_task(b) for b in sorted(blocks, key=lambda b: -b["seconds"])],
                "highlights": [], "blockers": [], "tomorrow": [], "insights": fallback_insights(analysis)}

    if not blocks:
        return {**fallback(), "tasks": []}, "skip"
    return runner.run(db, llm, model, "day", DAY_SYSTEM, payload, DAY_SHAPE,
                      _day_validator(blocks, allowed, tickets), fallback, _repair_day(blocks, allowed, tickets))


# --- suggestions ----------------------------------------------------------------------------------------
OPT_SYSTEM = (
    "You coach one person on using their working day better. The OBSERVATIONS were measured by the tracker. "
    "Pick the 3 to 5 that matter most and turn each into one specific, practical suggestion (what to change and "
    "when), quoting the observation's numbers exactly. Use the observation's metric key. Be kind and concrete. "
    "Skip anything the person marked as not useful before.")
OPT_SHAPE = '{"suggestions": [{"text": "...", "metric": "one of the metric keys"}]}'


def suggest(db, llm, model, payload: dict, tickets: set[str]) -> tuple[list[dict], str]:
    allowed = guards.allowed_numbers(payload) | guards.ADVICE_NUMBERS

    def validate(data):
        errors, out = [], []
        items = data.get("suggestions")
        if not isinstance(items, list) or not 1 <= len(items) <= 5:
            return {}, ["'suggestions' must be a list of 1 to 5 items"]
        for s in items:
            text, metric = str((s or {}).get("text") or "").strip(), (s or {}).get("metric")
            if metric not in METRICS:
                errors.append(f"metric must be one of {METRICS}, got {metric!r}")
            errors += [f"suggestion: {p}" for p in guards.problems(text, allowed, tickets)]
            out.append({"text": text[:400], "metric": metric})
        return {"suggestions": out}, errors

    def repair(data):
        out = []
        for s in data.get("suggestions") or []:
            text = guards.scrub(str((s or {}).get("text") or ""), allowed, tickets)
            if text and (s or {}).get("metric") in METRICS:
                out.append({"text": text, "metric": s["metric"]})
        return {"suggestions": out} if out else None

    view = {**payload, "observations": [{k: o[k] for k in ("metric", "observation")} for o in payload["observations"]]}
    out, status = runner.run(db, llm, model, "optimise", OPT_SYSTEM, view, OPT_SHAPE, validate,
                             lambda: {"suggestions": fallback_suggestions(payload["observations"])}, repair)
    return out["suggestions"], status


def fallback_suggestions(observations: list[dict]) -> list[dict]:
    return [{"metric": o["metric"], "text": o["advice"]} for o in observations if o["advice"]][:5]


# --- team day / week ------------------------------------------------------------------------------------
TEAM_SYSTEM = ("You write a manager's summary of their team's day from each person's report and numbers: "
               "overall progress, who carried the main work, anyone overloaded (overtime, meeting-heavy) or "
               "under-used, risks and blockers, and 1-3 suggestions for the team. Refer to people by name.")
TEAM_SHAPE = '{"summary": "...", "risks": ["..."], "suggestions": ["..."]}'
WEEK_SYSTEM = ("You write a weekly (or monthly) status summary from daily summaries: main achievements, how "
               "time was spent and how that changed across the days, and 1-3 suggestions for next period.")
WEEK_SHAPE = '{"summary": "...", "trends": ["..."], "suggestions": ["..."]}'


def rollup(db, llm, model, level: str, payload: dict, tickets: set[str], fallback_text: str) -> tuple[dict, str]:
    system, shape, lists = ((TEAM_SYSTEM, TEAM_SHAPE, {"risks": 5, "suggestions": 3}) if level == "team"
                            else (WEEK_SYSTEM, WEEK_SHAPE, {"trends": 5, "suggestions": 3}))
    allowed = guards.allowed_numbers(payload)
    tickets = tickets | guards.refs_in(payload)
    return runner.run(db, llm, model, level, system, payload, shape,
                      _text_validator(allowed, tickets, {"summary": 1500}, lists),
                      lambda: {"summary": fallback_text, **{k: [] for k in lists}},
                      _scrubbing_repair(allowed, tickets, ["summary"], lists))


# --- rule suggestions -----------------------------------------------------------------------------------
RULE_SYSTEM = ("Classify a website by what people at work usually use it for. Pick exactly one category from "
               "the list and give a short reason.")


def suggest_rule(db, llm, model, domain: str, titles: list[str], categories: list[str]) -> dict | None:
    payload = {"domain": domain, "page_titles": titles[:5], "categories": categories}

    def validate(data):
        cat = data.get("category")
        if cat not in categories:
            return {}, [f"category must be one of {categories}"]
        return {"category": cat, "reason": str(data.get("reason") or "")[:300]}, []

    out, status = runner.run(db, llm, model, "rule", RULE_SYSTEM, payload, '{"category": "...", "reason": "..."}',
                             validate, lambda: {})
    return out if status == "ok" else None
