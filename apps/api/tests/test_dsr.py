import json
import re
from datetime import UTC, date, datetime, timedelta

import pytest

from app.ai import guards, llm as llm_mod
from app.models import CalendarEvent, Device, DsrReport, RawEvent, WorkAction

DAY = date(2026, 10, 21)
T0 = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)  # 09:00 Asia/Karachi


class FakeLLM:
    """Answers each level sensibly from the facts; `day_reply` can override the day-level answers in order."""

    def __init__(self, day_replies=None):
        self.calls = []
        self.day_replies = list(day_replies or [])

    def __call__(self, system, user):
        facts = json.loads(user.split("FACTS (JSON):\n", 1)[1].split("\n\nReply as JSON", 1)[0])
        self.calls.append((system[:40], facts))
        if system.startswith("You write a person's Daily Status Report"):
            if self.day_replies:
                r = self.day_replies.pop(0)
                return r(facts) if callable(r) else r
            ids = [b["id"] for b in facts["blocks"]]
            return json.dumps({"tasks": [{"title": "Support tickets and coding", "block_ids": ids,
                                          "summary": "Worked through the ticket queue.", "status": "in_progress"}],
                               "highlights": ["Ticket queue handled"], "blockers": [], "tomorrow": ["Continue"],
                               "insights": "A focused day."})
        if system.startswith("You coach"):
            return json.dumps({"suggestions": [{"text": "Keep a quiet hour for focus.", "metric": "deep_focus"}]})
        if system.startswith("You summarise one piece"):
            return json.dumps({"summary": "Handled it."})
        return json.dumps({"summary": "Section done."})


@pytest.fixture()
def person(db, make_user):
    from app.models import Team
    team = Team(name="Support", timezone="Asia/Karachi")
    db.add(team)
    db.commit()
    u = make_user("ali@example.com", team_id=team.id)
    dev = Device(user_id=u.id, hostname="PC", token_hash="x" * 64)
    db.add(dev)
    db.commit()

    def ev(seq, minute, secs, **kw):
        db.add(RawEvent(device_id=dev.id, user_id=u.id, seq=seq, started_at=T0 + timedelta(minutes=minute),
                        duration_s=secs, kind=kw.pop("kind", "active"), **kw))
    ev(1, 0, 3600, app="code.exe", title="service.py - tracker")
    ev(2, 60, 1500, app="chrome.exe", domain="mantis.example.com", title="0012345: Login fails - MantisBT",
       url="https://mantis.example.com/view.php?id=12345")
    ev(3, 85, 600, app="chrome.exe", domain="mail.google.com", title="Inbox")
    ev(4, 95, 900, app="chrome.exe", domain="youtube.com", title="Music")
    db.add(WorkAction(ext_key="mantis:12345:note:1", user_id=u.id, day=DAY, source="mantis", action="responded",
                      object_id="12345", object_title="Login fails", at=T0 + timedelta(minutes=70),
                      meta={"note_text": "Asked the client for logs"}))
    db.add(CalendarEvent(user_id=u.id, day=DAY, ext_id="e1", title="Standup", attendees=5,
                         started_at=T0 + timedelta(hours=3), ended_at=T0 + timedelta(hours=3, minutes=15)))
    db.commit()
    return u


def generate(db, person, fake):
    from app.dsr.service import generate as gen
    llm_mod.override = fake
    try:
        return gen(db, person, DAY)
    finally:
        llm_mod.override = None


def test_draft_built_from_blocks_with_code_minutes(db, person):
    r = generate(db, person, FakeLLM())
    assert r.status == "draft" and r.ai_status == "ok"
    by_title = {t["title"]: t for t in r.content["tasks"]}
    task, email = by_title["Support tickets and coding"], by_title["Email and chat"]
    assert by_title["Meetings and calls"]["seconds"] == 900  # the standup, from the calendar analysis
    productive = [b for b in r.facts["blocks"] if b["klass"] == "productive"]
    assert task["seconds"] == sum(b["seconds"] for b in productive)  # time comes from code, not the model
    assert task["refs"] == ["12345"]
    # Email and chat is a standard task built by code from the communication blocks.
    assert email["title"] == "Email and chat" and email["seconds"] == 600
    used = sorted(b for t in r.content["tasks"] for b in t["block_ids"])
    assert used == sorted(b["id"] for b in r.facts["blocks"])
    assert r.content["work_output"]["mantis"] == {"responded": 1, "tickets": 1}
    assert [m["title"] for m in r.content["meetings"]] == ["Standup"]
    assert r.content["suggestions"][0]["metric"] == "deep_focus"
    assert "youtube.com" not in json.dumps(r.content["tasks"])  # non-work never becomes a task
    assert r.original == r.content


def test_invented_number_is_retried(db, person):
    def bad(facts):
        ids = [b["id"] for b in facts["blocks"]]
        return json.dumps({"tasks": [{"title": "Coding", "block_ids": ids, "summary": "Spent 7 hours coding.",
                                      "status": "done"}], "highlights": [], "blockers": [], "tomorrow": [], "insights": "ok"})
    fake = FakeLLM([bad])
    r = generate(db, person, fake)
    day_calls = [c for c in fake.calls if c[0].startswith("You write a person's Daily")]
    assert len(day_calls) == 2 and r.ai_status == "ok"
    assert "7 hours" not in json.dumps(r.content)


def test_always_wrong_is_repaired_then_scrubbed(db, person):
    def bad(facts):
        first = facts["blocks"][0]["id"]
        return json.dumps({"tasks": [{"title": "Coding", "block_ids": [first],
                                      "summary": "Fixed #999 for 42 hours. Reviewed code.", "status": "done"}],
                           "highlights": ["Closed #999"], "blockers": [], "tomorrow": [], "insights": "Good."})
    r = generate(db, person, FakeLLM([bad, bad, bad]))
    assert r.ai_status == "partial"
    text = json.dumps(r.content["tasks"]) + json.dumps(r.content["highlights"])
    assert "#999" not in text and "42" not in text and "Reviewed code." in text
    # every block still ends up in exactly one task
    used = [b for t in r.content["tasks"] for b in t["block_ids"]]
    assert sorted(used) == sorted(b["id"] for b in r.facts["blocks"])


def test_model_down_gives_code_written_report(db, person):
    def down(system, user):
        raise llm_mod.LLMUnavailable("connection refused")
    r = generate(db, person, down)
    assert r.ai_status == "fallback" and r.content["tasks"]
    assert any("12345" in t["title"] for t in r.content["tasks"])
    assert "shift" in r.content["insights"]


def test_submitted_report_is_never_overwritten(db, person):
    r = generate(db, person, FakeLLM())
    r.status = "submitted"
    r.content = {**r.content, "highlights": ["My own words"]}
    db.commit()
    again = generate(db, person, FakeLLM())
    assert again.content["highlights"] == ["My own words"]


def test_cache_reuses_item_summaries(db, person):
    generate(db, person, FakeLLM())
    fake = FakeLLM()
    generate(db, person, fake)
    assert not [c for c in fake.calls if c[0].startswith("You summarise one piece")]


def test_guards():
    allowed = guards.allowed_numbers({"seconds": 5400, "title": "Meeting at 11:30", "count": 4})
    assert guards.bad_numbers("Spent 1h30m (90 minutes, 1.5 hours) on 4 items at 11:30", allowed) == []
    assert guards.bad_numbers("Spent 3 hours", allowed) == ["3"]
    assert guards.bad_refs("Fixed #12345 and #7", {"12345"}) == ["7"]
    assert guards.scrub("Good day. Closed 9 tickets. Done.", allowed, set()) == "Good day. Done."
