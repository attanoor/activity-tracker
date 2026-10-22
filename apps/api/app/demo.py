"""Demo data: a 'Demo Support' team with three people and realistic tracked days.

  python -m app.cli demo [days]     create or refresh (default: today and the 6 days before)
  python -m app.cli demo-remove     delete every demo person and their data

Demo accounts use @demo.local addresses, so no real email can be sent to them. Passwords are written to
.local/secrets/demo-users.txt.
"""

import random
import secrets
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.models import CalendarEvent, Device, RawEvent, Team, User, WorkAction
from app.security import hash_password, token_hash

TZ = "Asia/Karachi"
TEAM = "Demo Support"
DOMAIN = "demo.local"
PEOPLE = [
    ("demo.manager", "Sana Malik", "manager", None),
    ("demo.support", "Bilal Ahmed", "resource", "support"),
    ("demo.dev", "Ayesha Khan", "resource", "developer"),
    ("demo.analyst", "Omar Farooq", "resource", "analyst"),
]

TICKETS = [("10231", "Payment page times out for club members"), ("10240", "Member import fails on special characters"),
           ("10244", "POS receipt shows wrong VAT"), ("10252", "Booking calendar not loading in Safari"),
           ("10260", "Add export of monthly invoices"), ("10263", "Password reset email not received")]
# Demo clubs: River Oaks has its own website; Lakeside is picked inside the shared backoffice.
CLUBS = {
    "River Oaks Country Club": {"web": "riveroaks-cc.demo", "email": "riveroakscc.demo", "project": "River Oaks POS"},
    "Lakeside Golf Club": {"web": None, "email": "lakesidegolf.demo", "project": "Lakeside Membership"},
}
TICKET_CLUB = {"10231": "River Oaks Country Club", "10240": "Lakeside Golf Club", "10244": "River Oaks Country Club",
               "10252": "Lakeside Golf Club", "10260": "River Oaks Country Club", "10263": "Lakeside Golf Club"}
TICKET_CATEGORY = {"10231": "Bug", "10240": "Bug", "10244": "Bug", "10252": "Bug", "10260": "Feature Request",
                   "10263": "Support"}
BACKOFFICE = "backoffice.northstar.demo"
SECTIONS = [["Membership", "Billing", "Dues setup"], ["POS", "Menu items"], ["Tee Times", "Rules"],
            ["Reports", "Monthly invoices"], ["Membership", "Member import"]]
EMAIL_SUBJECTS = {"River Oaks Country Club": ["Re: Payment failures this morning", "Invoice export timeline"],
                  "Lakeside Golf Club": ["Re: Member import file", "Booking calendar issue"]}

# (app, domain, title, klass hint) building blocks per persona; titles carry the details the AI needs.
WORK = {
    "support": [
        ("chrome.exe", "mantis.{d}", "0{t}: {s} - MantisBT", 6),
        ("chrome.exe", "mail.google.com", "Inbox (12) - bilal@club.com - Gmail", 3),
        ("chrome.exe", "chat.google.com", "Google Chat", 2),
        ("chrome.exe", "docs.google.com", "Support runbook - Google Docs", 1),
        ("explorer.exe", None, "Downloads", 1),
        ("chrome.exe", "stackoverflow.com", "Safari date input not working - Stack Overflow", 1),
        ("chrome.exe", BACKOFFICE, "NorthStar Backoffice", 4),
        ("chrome.exe", "riveroaks-cc.demo", "River Oaks Country Club - Members", 2),
        ("chrome.exe", "mail.google.com", "{subj} - bilal@club.com - Gmail", 3),
    ],
    "developer": [
        ("code.exe", None, "payments.py - club-portal - Visual Studio Code", 7),
        ("chrome.exe", "github.com", "Pull request #318: Fix payment timeout - club-portal", 3),
        ("windowsterminal.exe", None, "pytest - club-portal", 2),
        ("chrome.exe", "mantis.{d}", "0{t}: {s} - MantisBT", 2),
        ("chrome.exe", "stackoverflow.com", "requests timeout retry - Stack Overflow", 1),
        ("chrome.exe", "mail.google.com", "Inbox - ayesha@club.com - Gmail", 1),
    ],
    "analyst": [
        ("chrome.exe", "docs.google.com", "Q4 membership report - Google Sheets", 4),
        ("chrome.exe", "figma.com", "Booking flow redesign - Figma", 3),
        ("chrome.exe", "mail.google.com", "Inbox - omar@club.com - Gmail", 2),
        ("chrome.exe", "docs.google.com", "Requirements: invoice export - Google Docs", 2),
        ("chrome.exe", "youtube.com", "Lo-fi beats to work to - YouTube", 1),
        ("chrome.exe", "news.ycombinator.com", "Hacker News", 1),
        ("chrome.exe", BACKOFFICE, "NorthStar Backoffice", 3),
    ],
}
MEETINGS = {
    "support": [("Daily standup", time(9, 30), 15, 6), ("River Oaks: payment issues call", time(15, 0), 30, 3)],
    "developer": [("Daily standup", time(9, 30), 15, 6), ("Code review: payments", time(14, 0), 45, 3)],
    "analyst": [("Daily standup", time(9, 30), 15, 6), ("Booking redesign review", time(11, 0), 60, 5),
                ("Q4 report with finance", time(12, 0), 45, 4), ("Invoice export scoping", time(16, 0), 30, 3)],
}


def _user(db: Session, local: str, name: str, role: str, team_id: int | None, creds: list) -> User:
    email = f"{local}@{DOMAIN}"
    u = db.scalar(select(User).where(User.email == email))
    if not u:
        pw = secrets.token_urlsafe(10)
        u = User(email=email, name=name, role=role, team_id=team_id, password_hash=hash_password(pw),
                 timezone=None, mantis_username=local)
        db.add(u)
        db.flush()
        creds.append(f"{email}  {pw}  ({role})")
    return u


def _device(db: Session, u: User) -> Device:
    d = db.scalar(select(Device).where(Device.user_id == u.id, Device.hostname == "DEMO-PC"))
    if not d:
        d = Device(user_id=u.id, hostname="DEMO-PC", token_hash=token_hash(secrets.token_urlsafe(16)),
                   last_seen_at=datetime.now(ZoneInfo(TZ)))
        db.add(d)
        db.flush()
    return d


def _day(db: Session, u: User, dev: Device, persona: str, day: date, until: datetime | None) -> None:
    rnd = random.Random(f"{u.email}{day}")
    z = ZoneInfo(TZ)
    lo = datetime.combine(day, time.min, z)
    db.execute(delete(RawEvent).where(RawEvent.device_id == dev.id, RawEvent.started_at >= lo,
                                      RawEvent.started_at < lo + timedelta(days=1)))
    db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == u.id, CalendarEvent.day == day))
    db.execute(delete(WorkAction).where(WorkAction.user_id == u.id, WorkAction.day == day))
    if day.weekday() >= 5:
        return
    meetings = []
    for i, (title, start, mins, people) in enumerate(MEETINGS[persona]):
        if title != "Daily standup" and rnd.random() < 0.3:
            continue
        a = datetime.combine(day, start, z)
        meetings.append((a, a + timedelta(minutes=mins)))
        guests = [CLUBS["River Oaks Country Club"]["email"]] if title.startswith("River Oaks") else []
        db.add(CalendarEvent(user_id=u.id, day=day, ext_id=f"demo-{persona}-{day}-{i}", title=title, started_at=a,
                             ended_at=a + timedelta(minutes=mins), attendees=people, has_video=True,
                             organizer=f"demo.manager@{DOMAIN}", attendee_domains=guests))
    t = datetime.combine(day, time(9, rnd.randint(0, 12)), z)
    end = datetime.combine(day, time(18, rnd.randint(0, 25)), z)
    lunch = datetime.combine(day, time(13, rnd.randint(0, 15)), z)
    weights = WORK[persona]
    todays = rnd.sample(TICKETS, 3)
    seq = int(t.timestamp() * 1000)
    while t < end and (until is None or t < until):
        if lunch <= t < lunch + timedelta(minutes=50):
            t = lunch + timedelta(minutes=50)
            continue
        m = next((m for m in meetings if m[0] <= t < m[1]), None)
        if m:
            span = int((m[1] - t).total_seconds())
            db.add(RawEvent(device_id=dev.id, user_id=u.id, seq=seq, started_at=t, duration_s=span, kind="active",
                            app="chrome.exe", domain="meet.google.com", title="Meet - Google Chrome",
                            url="https://meet.google.com/abc-defg-hij"))
        else:
            app, dom, title, _ = rnd.choices(weights, [w[3] for w in weights])[0]
            tid, summ = rnd.choice(todays)
            club = rnd.choice(list(CLUBS))
            title = title.format(t=tid, s=summ, subj=rnd.choice(EMAIL_SUBJECTS[club]))
            dom = dom.format(d=DOMAIN) if dom else None
            url = context = None
            if dom:
                url = f"https://{dom}/view.php?id={tid}" if "mantis" in dom else f"https://{dom}/"
            if dom == BACKOFFICE:  # the club is picked inside the backoffice and shown in its header
                context = {"clubs": [club], "crumbs": rnd.choice(SECTIONS), "h1": "Backoffice"}
            elif dom == "riveroaks-cc.demo":
                context = {"clubs": ["River Oaks Country Club"], "crumbs": ["Members", "Directory"]}
            if rnd.random() < 0.06:
                span = rnd.randint(300, 900)
                db.add(RawEvent(device_id=dev.id, user_id=u.id, seq=seq, started_at=t, duration_s=span, kind="idle"))
            else:
                span = rnd.randint(60, 1500) if dom != "mail.google.com" else rnd.randint(40, 300)
                db.add(RawEvent(device_id=dev.id, user_id=u.id, seq=seq, started_at=t, duration_s=span, kind="active",
                                app=app, domain=dom, title=title, url=url, context=context))
            nxt = next((m[0] for m in meetings if t < m[0] < t + timedelta(seconds=span)), None)
            if nxt:
                span = int((nxt - t).total_seconds())
        t += timedelta(seconds=max(span, 30))
        seq += max(span, 30) * 1000

    def act(minute_of_day: int, source: str, action: str, oid: str, title: str, meta: dict):
        at = datetime.combine(day, time.min, z) + timedelta(minutes=minute_of_day)
        if until is not None and at > until:
            return
        db.add(WorkAction(ext_key=f"demo:{u.id}:{day}:{source}:{oid}:{action}:{minute_of_day}", user_id=u.id, day=day,
                          source=source, action=action, object_id=oid, object_title=title, at=at, meta=meta))
    def kind(tid):
        return {"project": CLUBS[TICKET_CLUB[tid]]["project"], "category": TICKET_CATEGORY[tid], "severity": "major",
                "priority": "normal"}
    if persona in ("support", "developer"):
        if persona == "support":
            act(580, "mantis", "reported", todays[2][0], todays[2][1], kind(todays[2][0]))
        for i, (tid, summ) in enumerate(todays):
            act(600 + i * 70, "mantis", "responded", tid, summ, {**kind(tid), "note_text": rnd.choice([
                "Reproduced on staging. Asked the client for the exact time of the failure.",
                "Root cause is the 30 second gateway timeout; fix in PR #318.",
                "Deployed the fix to staging, please verify.", "Need the CSV file that failed to import."])})
        act(700, "mantis", "took", todays[0][0], todays[0][1], {**kind(todays[0][0]), "to": u.mantis_username})
        if rnd.random() < 0.7:
            act(1000, "mantis", "resolved", todays[1][0], todays[1][1], {**kind(todays[1][0]), "from": "assigned",
                                                                        "to": "resolved"})
    for i in range(rnd.randint(4, 11)):
        reply = rnd.random() < 0.7
        club = rnd.choice(list(CLUBS))
        subject = rnd.choice(EMAIL_SUBJECTS[club])
        contact = {"email": f"gm@{CLUBS[club]['email']}", "name": f"General Manager, {club}"}
        me = {"email": f"{u.email}", "name": u.name}
        act(560 + i * 45, "gmail", "replied" if reply else "new_thread", f"thread-{day}-{subject}", subject,
            {"from": [me], "to": [contact], "cc": [], "to_domains": [CLUBS[club]["email"]], "recipients": 1,
             "snippet": "Thanks for the update, we will look at it today."})
        act(540 + i * 45, "gmail", "received", f"thread-{day}-{subject}", subject.removeprefix("Re: "),
            {"from": [contact], "to": [me], "cc": []})
    if persona == "analyst":
        act(640, "drive", "edited", "items/q4", "Q4 membership report", {"mime": "spreadsheet"})
        act(900, "drive", "commented", "items/req", "Requirements: invoice export", {"mime": "document"})
        if rnd.random() < 0.5:
            act(960, "drive", "created", "items/notes", "Booking review notes", {"mime": "document"})


def _clubs(db: Session) -> None:
    """The demo clubs, confirmed, with their website, email domain and Mantis project; plus the ticket cache."""
    from app.clients.learn import _client_for_name, add_identifier
    from app.models import Ticket
    for name, ids in CLUBS.items():
        c = _client_for_name(db, name)
        c.status = "confirmed"
        if ids["web"]:
            add_identifier(db, c, "web_domain", ids["web"], source="admin")
        add_identifier(db, c, "email_domain", ids["email"], source="admin")
        add_identifier(db, c, "mantis_project", ids["project"], source="admin")
    for tid, summ in TICKETS:
        t = db.get(Ticket, tid) or Ticket(id=tid)
        t.project, t.summary, t.category = CLUBS[TICKET_CLUB[tid]]["project"], summ, TICKET_CATEGORY[tid]
        db.add(t)
    db.flush()


def seed(db: Session, days: int = 7) -> list[str]:
    _clubs(db)
    team = db.scalar(select(Team).where(Team.name == TEAM))
    if not team:
        team = Team(name=TEAM, timezone=TZ, shift_start=time(9, 0), shift_end=time(18, 0), break_minutes=60)
        db.add(team)
        db.flush()
    creds: list[str] = []
    users = {p[0]: _user(db, p[0], p[1], p[2], team.id, creds) for p in PEOPLE}
    team.manager_id = users["demo.manager"].id
    now = datetime.now(ZoneInfo(TZ))
    for local, _, _, persona in PEOPLE:
        if not persona:
            continue
        dev = _device(db, users[local])
        for i in range(days - 1, -1, -1):
            d = now.date() - timedelta(days=i)
            _day(db, users[local], dev, persona, d, now if d == now.date() else None)
    db.commit()
    if creds:
        f = ROOT / ".local" / "secrets" / "demo-users.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a") as fh:
            fh.write("\n".join(creds) + "\n")
    return creds


E2E_TEAM = "E2E"
E2E_PEOPLE = [("e2e.resource", "Erin Resource", "resource"), ("e2e.manager", "Mark Manager", "manager"),
              ("e2e.admin", "Ada Admin", "admin")]


def e2e_setup(db: Session) -> dict:
    """Fresh accounts for the browser tests, with yesterday's tracked day and no report yet. Passwords are new on
    every run and returned (the caller writes them to .local/secrets/e2e.json)."""
    team = db.scalar(select(Team).where(Team.name == E2E_TEAM))
    if not team:
        team = Team(name=E2E_TEAM, timezone=TZ, shift_start=time(9, 0), shift_end=time(18, 0), break_minutes=60)
        db.add(team)
        db.flush()
    out = {}
    users = {}
    for local, name, role in E2E_PEOPLE:
        email = f"{local}@{DOMAIN}"
        u = db.scalar(select(User).where(User.email == email))
        pw = secrets.token_urlsafe(12)
        if not u:
            u = User(email=email, name=name, role=role, team_id=team.id, password_hash=hash_password(pw))
            db.add(u)
            db.flush()
        u.password_hash, u.active, u.role, u.team_id = hash_password(pw), True, role, team.id
        users[local] = u
        out[local] = {"email": email, "password": pw}
    team.manager_id = users["e2e.manager"].id
    r = users["e2e.resource"]
    from app.models import DsrReport
    db.execute(delete(DsrReport).where(DsrReport.user_id == r.id))
    dev = _device(db, r)
    _clubs(db)
    now = datetime.now(ZoneInfo(TZ))
    yesterday = now.date() - timedelta(days=1)
    while yesterday.weekday() >= 5:  # a working day
        yesterday -= timedelta(days=1)
    _day(db, r, dev, "developer", yesterday, None)
    # Yesterday may already be closed for changes; the manager reopens it, as they would in real use.
    empty = {"tasks": [], "highlights": [], "blockers": [], "tomorrow": [], "insights": "", "suggestions": [],
             "sections": {}, "items": {}, "meetings": [], "work_output": {}, "time_by_client": []}
    db.add(DsrReport(user_id=r.id, day=yesterday, content=empty, original=empty, ai_status="fallback",
                     reopened_by=users["e2e.manager"].id))
    db.commit()
    out["day"] = yesterday.isoformat()
    out["team_id"] = team.id
    out["resource_id"] = r.id
    return out


def remove(db: Session) -> int:
    users = list(db.scalars(select(User).where(User.email.like(f"%@{DOMAIN}"))))
    team = db.scalar(select(Team).where(Team.name == TEAM))
    if team:
        team.manager_id = None
        db.flush()
    for u in users:
        db.delete(u)
    db.flush()
    if team:
        db.delete(team)
    db.commit()
    return len(users)
