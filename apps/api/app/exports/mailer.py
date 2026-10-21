"""End-of-day email: each DSR to the person's manager (copy to the person), and a team digest."""

import smtplib
from email.message import EmailMessage
from html import escape

from sqlalchemy.orm import Session

from app import settings_store
from app.analysis.engine import fmt_hm
from app.exports.bundle import Bundle


class MailNotConfigured(Exception):
    pass


def send(db: Session, to: list[str], subject: str, text: str, html: str, attachments: list[tuple[str, bytes, str]] = (),
         cc: list[str] = ()) -> None:
    cfg = settings_store.get(db, "email")
    if not cfg["enabled"] or not cfg["host"] or not cfg["from_addr"]:
        raise MailNotConfigured("Email is not set up (Admin → Integrations → Email)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["from_addr"], ", ".join(to), subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30) as s:
        if cfg["starttls"]:
            s.starttls()
        password = settings_store.secret(db, "email", "password")
        if cfg["username"] and password:
            s.login(cfg["username"], password)
        s.send_message(msg)


def dsr_message(b: Bundle, reviewed: bool) -> tuple[str, str, str]:
    c, a = b.content, b.analysis
    flag = "" if reviewed else " (not reviewed by the person)"
    subject = f"DSR {b.user.name} {b.day:%d %b %Y}{flag}"
    lines = [f"Daily Status Report: {b.user.name}, {b.day:%A %d %B %Y}{flag}", ""]
    lines += [f"- {t['title']} ({fmt_hm(t['seconds'])}, {t['status'].replace('_', ' ')}): {t.get('summary', '')}" for t in c.get("tasks", [])]
    for title, key in (("Highlights", "highlights"), ("Blockers", "blockers"), ("Tomorrow", "tomorrow")):
        if c.get(key):
            lines += ["", f"{title}:"] + [f"- {x}" for x in c[key]]
    if c.get("insights"):
        lines += ["", c["insights"]]
    text = "\n".join(lines)
    bd = a["breakdown"]
    html = (f"<h2 style='font-family:Segoe UI,sans-serif'>DSR: {escape(b.user.name)}, {b.day:%d %b %Y}{escape(flag)}</h2>"
            f"<p style='font-family:Segoe UI,sans-serif;color:#475467'>Productive {fmt_hm(bd['productive'])} · "
            f"Meetings {fmt_hm(bd['meeting'])} · Email &amp; chat {fmt_hm(bd['communication'])} · Idle {fmt_hm(bd['idle'])}</p>"
            "<table style='font-family:Segoe UI,sans-serif;border-collapse:collapse' cellpadding='6'>"
            "<tr style='background:#12805A;color:#fff'><th align='left'>Task</th><th>Time</th><th>Status</th></tr>"
            + "".join(f"<tr style='border-bottom:1px solid #E4E7EC'><td><b>{escape(t['title'])}</b><br>{escape(t.get('summary', ''))}</td>"
                      f"<td>{fmt_hm(t['seconds'])}</td><td>{t['status'].replace('_', ' ')}</td></tr>" for t in c.get("tasks", []))
            + "</table>"
            + "".join(f"<h3 style='font-family:Segoe UI,sans-serif'>{title}</h3><ul>"
                      + "".join(f"<li>{escape(x)}</li>" for x in c[key]) + "</ul>"
                      for title, key in (("Highlights", "highlights"), ("Blockers", "blockers"), ("Tomorrow", "tomorrow"))
                      if c.get(key))
            + (f"<p style='font-family:Segoe UI,sans-serif'>{escape(c['insights'])}</p>" if c.get("insights") else ""))
    return subject, text, html


def digest_message(team_name: str, day, summary: dict, rows: list[dict]) -> tuple[str, str, str]:
    subject = f"Team {team_name}: daily summary {day:%d %b %Y}"
    text = summary.get("summary", "") + "\n\n" + "\n".join(
        f"- {r['name']}: report {r['report']}, productive {r['productive']}, meetings {r['meetings']}" for r in rows)
    html = (f"<h2 style='font-family:Segoe UI,sans-serif'>{escape(subject)}</h2>"
            f"<p style='font-family:Segoe UI,sans-serif'>{escape(summary.get('summary', ''))}</p>"
            + ("<h3>Risks</h3><ul>" + "".join(f"<li>{escape(x)}</li>" for x in summary.get("risks", [])) + "</ul>"
               if summary.get("risks") else "")
            + "<table cellpadding='6' style='font-family:Segoe UI,sans-serif;border-collapse:collapse'>"
            "<tr style='background:#12805A;color:#fff'><th align='left'>Person</th><th>Report</th><th>Productive</th><th>Meetings</th></tr>"
            + "".join(f"<tr><td>{escape(r['name'])}</td><td>{r['report']}</td><td>{r['productive']}</td><td>{r['meetings']}</td></tr>"
                      for r in rows) + "</table>")
    return subject, text, html
