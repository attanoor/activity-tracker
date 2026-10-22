"""The DSR as a one-to-two page PDF (reportlab, pure Python: no system libraries needed on Windows)."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.analysis.engine import fmt_hm
from app.exports.bundle import Bundle, day_fields
from app.exports.excel import BUCKET_LABELS

GREEN = colors.HexColor("#12805A")
LINE = colors.HexColor("#E4E7EC")


def dsr_pdf(b: Bundle, for_manager: bool = False) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"DSR {b.user.name} {b.day}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=GREEN, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8.5, textColor=colors.HexColor("#475467"))
    p = lambda t, s=body: Paragraph(escape(str(t)).replace("\n", "<br/>"), s)  # noqa: E731
    f, a = day_fields(b), b.analysis

    story = [p("Daily Status Report", h1),
             p(f"{b.user.name}{' · ' + b.team if b.team else ''} · {b.day:%A %d %B %Y} · "
               f"shift {a['shift']['start']}–{a['shift']['end']} · report {b.status}", small), Spacer(1, 4 * mm)]
    kpis = [["Worked", "Productive", "Meetings", "Email & chat", "Idle", "Overtime"],
            [fmt_hm(round(f["worked_hours"] * 3600)), fmt_hm(a["breakdown"]["productive"]), fmt_hm(a["breakdown"]["meeting"]),
             fmt_hm(a["breakdown"]["communication"]), fmt_hm(a["breakdown"]["idle"]),
             fmt_hm(a["overtime"]["before_s"] + a["overtime"]["after_s"])]]
    t = Table(kpis, colWidths=[29 * mm] * 6)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, 0), 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475467")),
                           ("FONTSIZE", (0, 1), (-1, 1), 13), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    story += [t]

    story.append(p("Tasks", h2))
    rows = [["Task", "Time", "Status"]] + [
        [Paragraph(f"<b>{escape(x['title'])}</b><br/>{escape(x.get('summary', ''))}", body),
         fmt_hm(x["seconds"]), x["status"].replace("_", " ")]
        for x in b.content.get("tasks", [])]
    t = Table(rows, colWidths=[132 * mm, 20 * mm, 26 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GREEN), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
                           ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(t)

    for title, key in (("Highlights", "highlights"), ("Blockers", "blockers"), ("Plan for tomorrow", "tomorrow")):
        items = b.content.get(key, [])
        if items:
            story.append(p(title, h2))
            story += [p(f"• {x}") for x in items]

    wo = [x for x in (f"Tickets: {f['tickets_reported']} reported, {f['tickets_responded']} responses, "
                      f"{f['tickets_resolved']} resolved ({f['tickets_touched']} touched)" if f["tickets_touched"] else "",
                      f"Email: {f['emails_sent']} sent ({f['email_replies']} replies) in {f['email_threads']} threads"
                      if f["emails_sent"] else "",
                      f"Documents: {f['docs_created']} created, {f['docs_edited']} edited"
                      if f["docs_created"] or f["docs_edited"] else "",
                      f"Meetings: {f['meeting_count']} ({fmt_hm(a['breakdown']['meeting'])})" if f["meeting_count"] else "") if x]
    if wo:
        story.append(p("Work output", h2))
        story += [p(f"• {x}") for x in wo]

    named = [r for r in b.analysis.get("by_client", {}).get("rows", []) if r["total_s"]]
    if named:
        story.append(p("Time by client", h2))
        rows = [["Client", "Total", "Website/backoffice", "Email", "Tickets", "Meetings", "Emails sent"]] + [
            [r["client"], fmt_hm(r["total_s"]), fmt_hm(r["web_s"]), fmt_hm(r["email_s"]), fmt_hm(r["tickets_s"]),
             fmt_hm(r["meetings_s"] + r["manual_s"]), str(r["emails_sent"])] for r in named]
        t = Table(rows, colWidths=[46 * mm, 18 * mm, 30 * mm, 18 * mm, 18 * mm, 22 * mm, 22 * mm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GREEN), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE)]))
        story.append(t)

    story.append(p("Where the shift went", h2))
    bd = a["breakdown"]
    t = Table([[BUCKET_LABELS[k], fmt_hm(v), f"{100 * v / a['shift']['seconds']:.0f}%"] for k, v in bd.items() if v],
              colWidths=[50 * mm, 25 * mm, 20 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]))
    story.append(t)

    if b.content.get("insights"):
        story += [p("Insights (AI)", h2), p(b.content["insights"])]
    if b.content.get("suggestions") and not for_manager:
        story.append(p("Suggestions (AI)", h2))
        story += [p(f"• {s['text']}") for s in b.content["suggestions"]]
    doc.build(story)
    return buf.getvalue()
