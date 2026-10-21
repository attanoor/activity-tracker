"""Default categories and rules. Idempotent: existing names and rules are left as the admin changed them."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, CategoryRule

CATEGORIES = {
    "Development": "productive",
    "Ticket work": "productive",
    "Documents": "productive",
    "Design": "productive",
    "Email": "communication",
    "Chat": "communication",
    "Meetings/Calls": "meeting",
    "Admin/Utilities": "neutral",
    "Search/Reference": "neutral",
    "Social media": "non_work",
    "Entertainment": "non_work",
    "Shopping": "non_work",
    "News": "non_work",
}

RULES = [
    ("domain", "github.com", "Development"),
    ("domain", "gitlab.com", "Development"),
    ("domain", "stackoverflow.com", "Development"),
    ("domain", "localhost", "Development"),
    ("domain", "127.0.0.1", "Development"),
    ("app", "code.exe", "Development"),
    ("app", "devenv.exe", "Development"),
    ("app", "idea64.exe", "Development"),
    ("app", "pycharm64.exe", "Development"),
    ("app", "windowsterminal.exe", "Development"),
    ("app", "powershell.exe", "Development"),
    ("domain", "*mantis*", "Ticket work"),
    ("title", r"\bmantisbt\b", "Ticket work"),
    ("domain", "docs.google.com", "Documents"),
    ("domain", "drive.google.com", "Documents"),
    ("app", "winword.exe", "Documents"),
    ("app", "excel.exe", "Documents"),
    ("app", "powerpnt.exe", "Documents"),
    ("domain", "figma.com", "Design"),
    ("domain", "mail.google.com", "Email"),
    ("domain", "outlook.office.com", "Email"),
    ("app", "outlook.exe", "Email"),
    ("domain", "chat.google.com", "Chat"),
    ("domain", "web.whatsapp.com", "Chat"),
    ("domain", "slack.com", "Chat"),
    ("app", "slack.exe", "Chat"),
    ("domain", "meet.google.com", "Meetings/Calls"),
    ("domain", "zoom.us", "Meetings/Calls"),
    ("domain", "teams.microsoft.com", "Meetings/Calls"),
    ("app", "zoom.exe", "Meetings/Calls"),
    ("app", "ms-teams.exe", "Meetings/Calls"),
    ("app", "explorer.exe", "Admin/Utilities"),
    ("domain", "google.com", "Search/Reference"),
    ("domain", "bing.com", "Search/Reference"),
    ("domain", "facebook.com", "Social media"),
    ("domain", "instagram.com", "Social media"),
    ("domain", "x.com", "Social media"),
    ("domain", "tiktok.com", "Social media"),
    ("domain", "youtube.com", "Entertainment"),
    ("domain", "netflix.com", "Entertainment"),
    ("domain", "amazon.com", "Shopping"),
    ("domain", "daraz.pk", "Shopping"),
]


def ensure_defaults(db: Session) -> None:
    existing = {c.name: c for c in db.scalars(select(Category))}
    for name, klass in CATEGORIES.items():
        if name not in existing:
            existing[name] = Category(name=name, klass=klass)
            db.add(existing[name])
    db.flush()
    have = {(r.field, r.pattern) for r in db.scalars(select(CategoryRule))}
    for field, pattern, cat in RULES:
        if (field, pattern) not in have:
            db.add(CategoryRule(field=field, pattern=pattern, category_id=existing[cat].id))
    db.commit()
