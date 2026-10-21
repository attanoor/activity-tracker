from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.pipeline.sessionise import Span, sessionise

TZ = "Asia/Karachi"
Z = ZoneInfo(TZ)
DAY = date(2026, 10, 21)


def at(h, m=0, s=0, day=DAY):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=Z)


def active(start, secs, app="chrome.exe", domain="github.com", title="PR #1", url=None):
    return Span(start, secs, "active", app, title, url, domain)


def test_merges_same_activity_across_short_gap():
    out = sessionise([active(at(9), 60), active(at(9, 1, 20), 60)], DAY, TZ)
    assert len(out) == 1
    assert out[0].started_at == at(9) and out[0].ended_at == at(9, 2, 20)
    assert out[0].duration_s == 140  # the 20 s gap is bridged


def test_long_gap_splits():
    out = sessionise([active(at(9), 60), active(at(9, 2), 60)], DAY, TZ)  # 60 s gap > 30 s
    assert len(out) == 2
    assert sum(s.duration_s for s in out) == 120


def test_different_domain_splits_and_app_case_is_ignored():
    out = sessionise([active(at(9), 60, app="Chrome.exe"), active(at(9, 1), 60, app="chrome.exe"),
                      active(at(9, 2), 60, domain="mail.google.com")], DAY, TZ)
    assert [s.domain for s in out] == ["github.com", "mail.google.com"]


def test_idle_is_its_own_session_and_breaks_merging():
    out = sessionise([active(at(9), 60), Span(at(9, 1), 600, "idle"), active(at(9, 11), 60)], DAY, TZ)
    assert [s.kind for s in out] == ["active", "idle", "active"]
    assert out[1].duration_s == 600


def test_overlap_is_never_double_counted():
    # A second device reports a span that overlaps the first by 30 s.
    out = sessionise([active(at(9), 120), active(at(9, 1, 30), 120, domain="figma.com")], DAY, TZ)
    assert sum(s.duration_s for s in out) == 210
    assert out[1].started_at == at(9, 2)


def test_fully_covered_span_is_dropped():
    out = sessionise([active(at(9), 600), active(at(9, 2), 60, domain="x.com")], DAY, TZ)
    assert len(out) == 1 and out[0].duration_s == 600


def test_midnight_crossover_is_split_between_days():
    prev = DAY - timedelta(days=1)
    span = active(at(23, 50, day=prev), 1200)  # 23:50 -> 00:10
    before = sessionise([span], prev, TZ)
    after = sessionise([span], DAY, TZ)
    assert before[0].duration_s == 600 and after[0].duration_s == 600
    assert after[0].started_at == at(0)


def test_private_and_paused_carry_no_details():
    leaky = Span(at(10), 300, "private", "chrome.exe", "Bank statement", "https://bank.example/acct", "bank.example")
    out = sessionise([leaky, Span(at(10, 5), 300, "paused", "x", "y")], DAY, TZ)
    assert [(s.kind, s.app, s.domain, s.title, s.paths) for s in out] == [
        ("private", None, None, None, []), ("paused", None, None, None, [])]


def test_titles_and_paths_ranked_by_time():
    out = sessionise([
        active(at(9), 60, title="A", url="https://github.com/org/a"),
        active(at(9, 1), 300, title="B", url="https://github.com/org/b"),
        active(at(9, 6), 60, title="A", url="https://github.com/org/a"),
    ], DAY, TZ)
    s = out[0]
    assert s.title == "B"
    assert s.titles == [["B", 300], ["A", 120]]
    assert s.paths[0] == ["/org/b", 300]


def test_domain_derived_from_url_when_missing():
    out = sessionise([Span(at(9), 60, "active", "msedge.exe", "Docs", "https://Docs.Google.com/d/1", None)], DAY, TZ)
    assert out[0].domain == "docs.google.com"


def test_unsorted_input():
    out = sessionise([active(at(10), 60, domain="b.com"), active(at(9), 60, domain="a.com")], DAY, TZ)
    assert [s.domain for s in out] == ["a.com", "b.com"]
