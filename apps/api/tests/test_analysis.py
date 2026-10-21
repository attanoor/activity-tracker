from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.analysis.engine import BUCKETS, MeetingIn, SessionIn, Shift, analyse, compare

TZ = "Asia/Karachi"
Z = ZoneInfo(TZ)
DAY = date(2026, 10, 21)


def at(h, m=0):
    return datetime(2026, 10, 21, h, m, tzinfo=Z)


def s(h1, m1, h2, m2, klass="productive", app="code.exe", domain=None, category="Development", title="x"):
    return SessionIn(at(h1, m1), at(h2, m2), klass, app, domain, title, category)


def run(sessions, meetings=(), shift=Shift()):
    return analyse(DAY, TZ, list(sessions), list(meetings), shift)


def test_breakdown_always_sums_to_shift():
    for sessions in ([], [s(9, 0, 18, 0)], [s(7, 0, 20, 0)], [s(10, 0, 11, 0), s(13, 0, 13, 30, "idle")],
                     [s(8, 0, 9, 30, "non_work"), s(17, 0, 19, 0, "communication")]):
        a = run(sessions)
        assert sum(a["breakdown"].values()) == 9 * 3600
        assert set(a["breakdown"]) == set(BUCKETS)


def test_empty_day_is_break_plus_away():
    a = run([])
    assert a["breakdown"]["break"] == 3600 and a["breakdown"]["away"] == 8 * 3600


def test_break_takes_longest_away_first_then_idle():
    sessions = [s(9, 0, 12, 0), s(12, 0, 12, 20, "idle"), s(12, 20, 13, 0), s(13, 40, 18, 0)]  # 40 min away at 13:00
    a = run(sessions)
    assert a["breakdown"]["break"] == 3600
    assert a["breakdown"]["away"] == 0 and a["breakdown"]["idle"] == 0  # 40 away + 20 idle became the break
    hour13 = next(h for h in a["hours"] if h["hour"] == 13)
    assert hour13["break"] == 40 * 60


def test_overtime_outside_shift():
    a = run([s(8, 30, 9, 0), s(9, 0, 18, 0), s(18, 0, 18, 45, "communication")])
    assert a["overtime"] == {"before_s": 1800, "after_s": 2700}


def test_meeting_attended_by_idle_counts_and_overwrites():
    sessions = [s(9, 0, 10, 0), s(10, 0, 10, 30, "idle"), s(10, 30, 18, 0)]
    a = run(sessions, [MeetingIn(1, "Standup", at(10, 0), at(10, 30), 5)])
    assert a["meetings"][0]["status"] == "attended"
    assert a["breakdown"]["meeting"] == 1800 and a["breakdown"]["idle"] == 0


def test_meeting_busy_elsewhere_is_unclear_and_not_counted():
    a = run([s(9, 0, 18, 0)], [MeetingIn(1, "Sync", at(11, 0), at(11, 30))])
    assert a["meetings"][0]["status"] == "unclear"
    assert a["breakdown"]["meeting"] == 0


def test_person_confirms_or_denies_meeting():
    confirmed = run([s(9, 0, 18, 0)], [MeetingIn(1, "Sync", at(11, 0), at(11, 30), attended=True)])
    assert confirmed["meetings"][0]["status"] == "confirmed" and confirmed["breakdown"]["meeting"] == 1800
    denied = run([s(9, 0, 10, 0)], [MeetingIn(1, "Sync", at(10, 0), at(10, 30), attended=False)])
    assert denied["meetings"][0]["status"] == "not_attended" and denied["breakdown"]["meeting"] == 0


def test_multitasking_meeting():
    sessions = [s(11, 0, 11, 10, "meeting", "chrome.exe", "meet.google.com"), s(11, 10, 11, 30, "productive")]
    a = run(sessions, [MeetingIn(1, "Review", at(11, 0), at(11, 30))])
    m = a["meetings"][0]
    assert m["status"] == "attended"  # 10 of 30 min on Meet is >= 30 %
    assert m["alongside"] == {"productive": 1200}


def test_adhoc_call_without_calendar_event():
    a = run([s(15, 0, 15, 20, "meeting", "zoom.exe")])
    assert len(a["adhoc_calls"]) == 1 and a["adhoc_calls"][0]["duration_s"] == 1200


def test_meeting_load_back_to_back_and_short_gaps():
    ms = [MeetingIn(1, "A", at(10, 0), at(10, 30), attended=True), MeetingIn(2, "B", at(10, 30), at(11, 0), attended=True),
          MeetingIn(3, "C", at(11, 20), at(12, 0), attended=True)]
    load = run([], ms)["meeting_load"]
    assert (load["count"], load["back_to_back"], load["short_gaps"], load["short_gap_s"]) == (3, 1, 1, 1200)


def test_focus_blocks_and_switches():
    # A 2-minute email check splits focus; interruptions up to 1 minute would not.
    sessions = [s(9, 0, 9, 40, domain="github.com"), s(9, 40, 9, 42, "communication", "chrome.exe", "mail.google.com", "Email"),
                s(9, 42, 10, 0), s(10, 0, 10, 50, app="code.exe")]
    a = run(sessions)
    assert a["focus"]["deep_blocks"] == 2  # 40 min, then 9:42-10:50 (68 min)
    assert a["focus"]["longest"]["seconds"] == 68 * 60
    assert a["switching"]["switches"] == 2  # github -> mail -> code.exe (code.exe -> code.exe is not a switch)
    assert a["communication_checks"] == {"Email": 1}


def test_one_minute_interruption_keeps_focus():
    sessions = [s(9, 0, 9, 20), s(9, 20, 9, 21, "communication", "chrome.exe", "mail.google.com", "Email"), s(9, 21, 9, 40)]
    assert run(sessions)["focus"]["deep_blocks"] == 1


def test_time_sinks_ranked():
    a = run([s(9, 0, 11, 0, "non_work", "chrome.exe", "youtube.com", "Entertainment"), s(11, 0, 12, 0)])
    assert a["top_targets"][0]["target"] == "youtube.com" and a["top_targets"][0]["seconds"] == 7200
    assert a["long_low_value"][0]["seconds"] == 7200


def test_custom_shift():
    a = run([s(10, 0, 19, 0)], shift=Shift(time(10, 0), time(19, 0), 30))
    assert sum(a["breakdown"].values()) == 9 * 3600 and a["expected_work_s"] == 8.5 * 3600


def test_compare_flags_big_differences_only():
    today = run([s(9, 0, 18, 0, "non_work")])
    usual = run([s(9, 0, 18, 0)])
    c = compare(today, [usual] * 3, [])
    assert c["non_work"]["flag"]["direction"] == "higher"
    assert c["productive"]["flag"]["direction"] == "lower"
    assert c["idle"]["flag"] is None
