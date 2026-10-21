"""Everything an export needs about one person-day, gathered once, plus the template field values."""

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.engine import fmt_hm
from app.dsr.service import compute_day
from app.models import DsrReport, Team, User


@dataclass
class Bundle:
    user: User
    team: str
    day: date
    tz: str
    content: dict
    status: str
    analysis: dict
    sessions: list
    actions: list


def gather(db: Session, user: User, day: date) -> Bundle:
    d = compute_day(db, user, day, rebuild=False)
    dsr = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day == day))
    team = db.get(Team, user.team_id) if user.team_id else None
    content = dsr.content if dsr else {"tasks": [], "highlights": [], "blockers": [], "tomorrow": [], "insights": "",
                                        "suggestions": [], "meetings": [], "work_output": d["work_output"]}
    return Bundle(user, team.name if team else "", day, d["tz"], content, dsr.status if dsr else "none",
                  d["analysis"], d["sessions"], d["actions"])


def hours(seconds: int) -> float:
    return round(seconds / 3600, 2)


def local(dt, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def day_fields(b: Bundle) -> dict:
    """Values for template fields that appear once per day."""
    wo, bd = b.content.get("work_output", {}), b.analysis["breakdown"]
    m, g, dr = wo.get("mantis", {}), wo.get("gmail", {}), wo.get("drive", {})
    meetings = [x for x in b.content.get("meetings", []) if x["status"] in ("confirmed", "attended", "multitasking")]
    return {
        "date": b.day, "name": b.user.name, "email": b.user.email, "team": b.team, "status": b.status,
        "worked_hours": hours(sum(bd[k] for k in ("productive", "meeting", "communication", "neutral", "non_work"))),
        "productive_hours": hours(bd["productive"]), "meeting_hours": hours(bd["meeting"]),
        "communication_hours": hours(bd["communication"]), "idle_hours": hours(bd["idle"]),
        "non_work_hours": hours(bd["non_work"]), "break_hours": hours(bd["break"]), "away_hours": hours(bd["away"]),
        "overtime_hours": hours(b.analysis["overtime"]["before_s"] + b.analysis["overtime"]["after_s"]),
        "meetings": "; ".join(f"{x['title']} ({fmt_hm(x['duration_s'])})" for x in meetings),
        "meeting_count": len(meetings),
        "tickets_reported": m.get("reported", 0), "tickets_responded": m.get("responded", 0),
        "tickets_resolved": m.get("resolved", 0) + m.get("closed", 0), "tickets_touched": m.get("tickets", 0),
        "emails_sent": g.get("replied", 0) + g.get("new_thread", 0), "email_replies": g.get("replied", 0),
        "email_threads": g.get("threads", 0),
        "docs_created": dr.get("created", 0), "docs_edited": dr.get("edited", 0),
        "highlights": "\n".join(b.content.get("highlights", [])), "blockers": "\n".join(b.content.get("blockers", [])),
        "tomorrow": "\n".join(b.content.get("tomorrow", [])), "remarks": b.content.get("insights", ""),
        "ai_summary": b.content.get("insights", ""),
        "ai_suggestions": "\n".join(s["text"] for s in b.content.get("suggestions", [])),
    }


def task_fields(t: dict) -> dict:
    """Values for template fields repeated per task row."""
    return {"task": t["title"], "task_summary": t.get("summary", ""), "hours": hours(t["seconds"]),
            "minutes": round(t["seconds"] / 60), "task_status": t["status"].replace("_", " "),
            "category": t.get("category") or "", "tickets": ", ".join(f"#{r}" for r in t.get("refs", []))}


FIELD_HELP = {
    "date": "Report date", "name": "Person", "email": "Email", "team": "Team", "status": "Report status",
    "task": "Task title (one row per task)", "task_summary": "Task summary", "hours": "Task hours",
    "minutes": "Task minutes", "task_status": "Done / in progress / blocked", "category": "Task category",
    "tickets": "Ticket numbers of the task", "worked_hours": "Hours worked in shift",
    "productive_hours": "Productive hours", "meeting_hours": "Meeting hours", "communication_hours": "Email/chat hours",
    "idle_hours": "Idle hours", "non_work_hours": "Non-work hours", "break_hours": "Break hours",
    "away_hours": "Away hours", "overtime_hours": "Overtime hours", "meetings": "Meetings list",
    "meeting_count": "Number of meetings", "tickets_reported": "Tickets reported",
    "tickets_responded": "Ticket responses", "tickets_resolved": "Tickets resolved/closed",
    "tickets_touched": "Tickets touched", "emails_sent": "Emails sent", "email_replies": "Email replies",
    "email_threads": "Email threads", "docs_created": "Docs created", "docs_edited": "Docs edited",
    "highlights": "Highlights", "blockers": "Blockers", "tomorrow": "Plan for tomorrow", "remarks": "AI insights",
    "ai_summary": "AI summary", "ai_suggestions": "AI suggestions",
}
TASK_FIELD_NAMES = {"task", "task_summary", "hours", "minutes", "task_status", "category", "tickets"}
