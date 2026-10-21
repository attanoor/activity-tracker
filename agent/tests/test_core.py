from datetime import UTC, datetime, timedelta

from tracker_agent.core import Coalescer, Sample, State, Tab, build_sample

T0 = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def t(sec):
    return T0 + timedelta(seconds=sec)


def a(sec, app="code.exe", title="x.py"):
    return Sample(t(sec), "active", app, title)


def feed(c, samples):
    out = []
    for s in samples:
        out += c.add(s)
    return out


# --- build_sample ----------------------------------------------------------------------------------
def test_browser_uses_extension_tab():
    tabs = {"chrome.exe": Tab("https://github.com/org/repo/pull/1", "PR 1")}
    s = build_sample(t(0), State(), "Chrome.exe", "PR 1 - Google Chrome", 0, False, tabs)
    assert (s.kind, s.app, s.domain, s.url, s.title) == ("active", "chrome.exe", "github.com",
                                                          "https://github.com/org/repo/pull/1", "PR 1")


def test_browser_without_tab_keeps_window_title_and_other_browser_tab_is_ignored():
    tabs = {"msedge.exe": Tab("https://x.com/", "X")}
    s = build_sample(t(0), State(), "chrome.exe", "Something - Google Chrome", 0, False, tabs)
    assert (s.url, s.domain, s.title) == (None, None, "Something - Google Chrome")


def test_non_http_tab_is_ignored():
    tabs = {"chrome.exe": Tab("chrome://settings", "Settings")}
    assert build_sample(t(0), State(), "chrome.exe", "Settings", 0, False, tabs).url is None


def test_domain_only_strips_path_and_title():
    tabs = {"chrome.exe": Tab("https://online.mybank.com/accounts/123", "Balance 4,000")}
    s = build_sample(t(0), State(domain_only=["mybank.com"]), "chrome.exe", "", 0, False, tabs)
    assert (s.url, s.title, s.domain) == ("https://online.mybank.com/", "online.mybank.com", "online.mybank.com")


def test_precedence_paused_private_locked_idle():
    tabs = {}
    assert build_sample(t(0), State(paused_until=t(60), private=True), "a", "b", 999, True, tabs).kind == "paused"
    assert build_sample(t(61), State(paused_until=t(60)), "a", "b", 0, False, tabs).kind == "active"
    assert build_sample(t(0), State(private=True), "a", "b", 999, True, tabs).kind == "private"
    assert build_sample(t(0), State(), "a", "b", 999, True, tabs).kind == "locked"
    assert build_sample(t(0), State(idle_threshold_s=300), "a", "b", 300, False, tabs).kind == "idle"
    assert build_sample(t(0), State(idle_threshold_s=300), "a", "b", 299, False, tabs).kind == "active"


def test_private_sample_has_no_details():
    s = build_sample(t(0), State(private=True), "chrome.exe", "Secret", 0, False, {"chrome.exe": Tab("https://s/", "S")})
    assert (s.app, s.title, s.url, s.domain) == (None, None, None, None)


# --- Coalescer -------------------------------------------------------------------------------------
def test_equal_samples_grow_one_span():
    c = Coalescer(interval_s=5, max_span_s=60)
    assert feed(c, [a(0), a(5), a(10)]) == []
    [e] = c.flush()
    assert e["duration_s"] == 15 and e["started_at"] == T0.isoformat() and e["app"] == "code.exe"


def test_change_closes_span_at_the_new_sample():
    c = Coalescer()
    [e] = feed(c, [a(0), a(5), a(10, title="y.py")])
    assert e["duration_s"] == 10
    [e2] = c.flush()
    assert e2["started_at"] == t(10).isoformat() and e2["title"] == "y.py"


def test_max_span_splits_continuously():
    c = Coalescer(interval_s=5, max_span_s=60)
    out = feed(c, [a(s) for s in range(0, 130, 5)])
    out += c.flush()
    assert sum(e["duration_s"] for e in out) == 130
    assert len(out) == 3
    # spans are back to back and seqs strictly increase
    assert [e["seq"] for e in out] == sorted({e["seq"] for e in out})


def test_sleep_gap_is_not_counted():
    c = Coalescer(interval_s=5, max_gap_s=20)
    out = feed(c, [a(0), a(5), a(600)])  # PC slept for ~10 minutes
    assert [e["duration_s"] for e in out] == [10]
    assert c.flush()[0]["started_at"] == t(600).isoformat()


def test_clock_going_backwards_closes_span():
    c = Coalescer()
    out = feed(c, [a(100), a(105), a(50)])
    assert [e["duration_s"] for e in out] == [10]


def test_idle_event_has_no_details():
    c = Coalescer()
    feed(c, [Sample(t(0), "idle"), Sample(t(5), "idle")])
    [e] = c.flush()
    assert e["kind"] == "idle" and e["app"] is None and e["duration_s"] == 10


def test_seq_is_start_millis():
    c = Coalescer()
    feed(c, [a(0)])
    assert c.flush()[0]["seq"] == int(T0.timestamp() * 1000)
