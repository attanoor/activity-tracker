from app.pipeline.categorise import Rule, categorise, order_rules

DEV, MAIL, FUN, TICKET, BROWSER = 1, 2, 3, 4, 5
RULES = order_rules([
    Rule(1, "app", "chrome.exe", BROWSER, "neutral"),
    Rule(2, "domain", "github.com", DEV, "productive"),
    Rule(3, "domain", "mail.google.com", MAIL, "communication"),
    Rule(4, "domain", "youtube.com", FUN, "non_work"),
    Rule(5, "domain", "*mantis*", TICKET, "productive"),
    Rule(6, "title", r"\bmantisbt\b", TICKET, "productive"),
    Rule(7, "app", "code*.exe", DEV, "productive"),
])


def cat(app=None, domain=None, title=None, kind="active", rules=RULES):
    return categorise(kind, app, domain, title, rules)


def test_domain_exact_and_subdomain():
    assert cat("chrome.exe", "github.com") == (DEV, "productive")
    assert cat("chrome.exe", "gist.github.com") == (DEV, "productive")


def test_domain_does_not_match_lookalike():
    assert cat(domain="notgithub.com") == (None, "neutral")


def test_domain_glob():
    assert cat("chrome.exe", "support.mantis.example.com") == (TICKET, "productive")


def test_domain_rule_beats_browser_app_rule():
    assert cat("chrome.exe", "youtube.com") == (FUN, "non_work")
    assert cat("chrome.exe", "unknown.site") == (BROWSER, "neutral")


def test_title_regex_case_insensitive():
    assert cat("chrome.exe", "tickets.local", "0012345: Login fails - MantisBT") == (TICKET, "productive")


def test_app_glob_case_insensitive():
    assert cat("code-insiders.exe") == (DEV, "productive")
    assert cat("CODE.EXE") == (DEV, "productive")


def test_priority_overrides_specificity():
    rules = order_rules(RULES + [Rule(8, "app", "chrome.exe", MAIL, "communication", priority=10)])
    assert cat("chrome.exe", "github.com", rules=rules) == (MAIL, "communication")


def test_bad_regex_is_ignored_not_raised():
    rules = order_rules([Rule(1, "title", "([", DEV, "productive")])
    assert cat(title="anything", rules=rules) == (None, "neutral")


def test_non_active_kinds():
    assert cat(kind="idle") == (None, "idle")
    assert cat(kind="locked") == (None, "away")
    assert cat(kind="private") == (None, "private")
    assert cat(kind="paused") == (None, "paused")
