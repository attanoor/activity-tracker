from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLES = ("resource", "manager", "admin")
# Productivity classes a category can carry. Non-active session kinds get their own class (see pipeline).
KLASSES = ("productive", "communication", "meeting", "neutral", "non_work")
EVENT_KINDS = ("active", "idle", "locked", "private", "paused")


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", use_alter=True, name="fk_teams_manager_id_users"))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    shift_start: Mapped[time] = mapped_column(Time, default=time(9, 0))
    shift_end: Mapped[time] = mapped_column(Time, default=time(18, 0))
    break_minutes: Mapped[int] = mapped_column(Integer, default=60)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="resource")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    # Overrides the team timezone when set.
    timezone: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Identities in other systems, for crediting work output. Empty = derive (email, email local part).
    mantis_username: Mapped[str | None] = mapped_column(String(120))
    google_email: Mapped[str | None] = mapped_column(String(254))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnrolCode(Base):
    __tablename__ = "enrol_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawEvent(Base):
    """One coalesced span reported by a device: the agent already merges its 5 s samples."""

    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_raw_events_device_seq"),
        Index("ix_raw_events_user_started", "user_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    app: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255))
    # What the page showed (headings, breadcrumb, club name), read by the extension; never typed values.
    context: Mapped[dict | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    klass: Mapped[str] = mapped_column(String(16))


class CategoryRule(Base):
    __tablename__ = "category_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    # "domain" (exact, subdomain or glob), "app" (process glob) or "title" (regex).
    field: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivitySession(Base):
    __tablename__ = "activity_sessions"
    __table_args__ = (Index("ix_activity_sessions_user_day", "user_id", "day"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    app: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255))
    # Title with the most time in this session; `titles` keeps the top few with seconds.
    title: Mapped[str | None] = mapped_column(Text)
    titles: Mapped[list] = mapped_column(JSONB, default=list)
    paths: Mapped[list] = mapped_column(JSONB, default=list)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    klass: Mapped[str] = mapped_column(String(16))
    # Page context: the club read from the page, the section path with the most time, and the top few.
    club: Mapped[str | None] = mapped_column(String(200))
    section: Mapped[str | None] = mapped_column(Text)
    contexts: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class Setting(Base):
    """Key/value configuration edited in Admin. Secret values are stored encrypted (see app.settings_store)."""

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GoogleToken(Base):
    """Per-person Google OAuth refresh token (encrypted), used when the admin chose per-user connection."""

    __tablename__ = "google_tokens"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    google_email: Mapped[str] = mapped_column(String(254))
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("user_id", "ext_id", name="uq_calendar_events_user_ext"),
                      Index("ix_calendar_events_user_day", "user_id", "day"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    ext_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attendees: Mapped[int] = mapped_column(Integer, default=0)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    organizer: Mapped[str | None] = mapped_column(String(254))
    # The person's own answer to "did you attend?" when activity made it unclear; None = not answered.
    attended: Mapped[bool | None] = mapped_column(Boolean)
    attendee_domains: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class WorkAction(Base):
    """One thing a person did in another system: a ticket note, a sent email, a document edit."""

    __tablename__ = "work_actions"
    __table_args__ = (Index("ix_work_actions_user_day", "user_id", "day"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ext_key: Mapped[str] = mapped_column(String(255), unique=True)  # makes every sync idempotent
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))   # mantis | gmail | drive
    action: Mapped[str] = mapped_column(String(32))   # reported, responded, resolved, sent, replied, edited ...
    object_id: Mapped[str] = mapped_column(String(255))
    object_title: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class DayAnalysis(Base):
    __tablename__ = "day_analyses"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DsrReport(Base):
    __tablename__ = "dsr_reports"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_dsr_reports_user_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | submitted | sent
    ai_status: Mapped[str] = mapped_column(String(16), default="ok")   # ok | partial | fallback
    content: Mapped[dict] = mapped_column(JSONB)       # what the person edits and submits
    original: Mapped[dict] = mapped_column(JSONB)      # the AI's draft, kept for audit
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)  # what the draft was built from
    model: Mapped[str | None] = mapped_column(String(80))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reopened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AiCache(Base):
    __tablename__ = "ai_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of level + model + input
    level: Mapped[str] = mapped_column(String(16))
    output: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Summary(Base):
    """AI summaries above one person-day: team days, and person or team weeks and months."""

    __tablename__ = "summaries"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "period", "start_day", name="uq_summaries"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(8))     # user | team
    scope_id: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(8))    # day | week | month
    start_day: Mapped[date] = mapped_column(Date)
    content: Mapped[dict] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SuggestionFeedback(Base):
    __tablename__ = "suggestion_feedback"
    __table_args__ = (UniqueConstraint("user_id", "day", "text_hash", name="uq_suggestion_feedback"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    text_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    useful: Mapped[bool] = mapped_column(Boolean)


class RuleSuggestion(Base):
    __tablename__ = "rule_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text, default="")
    seconds_seen: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExcelTemplate(Base):
    __tablename__ = "excel_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    file_name: Mapped[str] = mapped_column(String(255))  # stored under .local/templates
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(Base):
    """Makes scheduled work run once per key (e.g. dsr:2026-10-22:5), even across worker restarts."""

    __tablename__ = "job_runs"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class Client(Base):
    """A club (customer). Learned from domains, page text, emails and Mantis; confirmed by an admin."""

    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="suggested")  # suggested | confirmed | ignored
    notes: Mapped[str] = mapped_column(Text, default="")
    seconds_seen: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientIdentifier(Base):
    """One way to recognise a client: a web or email domain, an address, a name alias, a Mantis project."""

    __tablename__ = "client_identifiers"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_client_identifiers_kind_value"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # web_domain | email_domain | email_address | name_alias | mantis_project
    value: Mapped[str] = mapped_column(String(255))  # stored lower-case
    source: Mapped[str] = mapped_column(String(16), default="learned")  # learned | admin | import


class Ticket(Base):
    """Mantis tickets seen in syncs or in the browser, so time on a ticket page maps to its project (club)."""

    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    project: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(120))
    severity: Mapped[str | None] = mapped_column(String(40))
    priority: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ManualEntry(Base):
    """Work the tracker could not see (a site visit, a phone call away from the PC), logged by the person."""

    __tablename__ = "manual_entries"
    __table_args__ = (Index("ix_manual_entries_user_day", "user_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))  # call | site_visit | meeting | other
    title: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
