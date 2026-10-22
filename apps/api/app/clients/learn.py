"""Suggests clients and identifiers from what the team actually worked on. Nothing is used for attribution
until an admin confirms the client (Admin -> Clients).

Sources: websites with 10+ minutes that no category rule explains, club names read from pages, external email
domains with 2+ messages, Mantis projects. A suggestion attaches to an existing client when its name matches,
otherwise it creates a 'suggested' client.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import settings_store
from app.clients.domains import clean_host, email_domain, guess_name_from_domain, is_external, norm_name
from app.models import ActivitySession, Client, ClientIdentifier, Ticket, WorkAction

MIN_WEB_S = 600
MIN_EMAILS = 2


def _client_for_name(db: Session, name: str) -> Client:
    key = norm_name(name)
    for c in db.scalars(select(Client)):
        if norm_name(c.name) == key:
            return c
    alias = db.scalar(select(ClientIdentifier).where(ClientIdentifier.kind == "name_alias", ClientIdentifier.value == key))
    if alias:
        return db.get(Client, alias.client_id)
    c = Client(name=name.strip()[:200], status="suggested")
    db.add(c)
    db.flush()
    return c


def add_identifier(db: Session, client: Client, kind: str, value: str, source: str = "learned") -> bool:
    value = value.strip().lower()
    if not value or db.scalar(select(ClientIdentifier).where(ClientIdentifier.kind == kind, ClientIdentifier.value == value)):
        return False
    db.add(ClientIdentifier(client_id=client.id, kind=kind, value=value, source=source))
    db.flush()
    return True


def learn(db: Session, since: date, namer=None) -> dict:
    """`namer(domain, hints) -> name | None` may be an LLM; default guesses from the domain."""
    cfg = settings_store.get(db, "clients")
    internal = {d.lower() for d in cfg["internal_domains"]}
    extra_public = {d.lower() for d in cfg["extra_public_domains"]}
    known = {(k, v) for k, v in db.execute(select(ClientIdentifier.kind, ClientIdentifier.value))}
    added = Counter()

    # 1. Websites no category rule explains, or that showed a club name.
    rows = db.execute(select(ActivitySession.domain, ActivitySession.club, func.sum(ActivitySession.duration_s),
                             func.array_agg(ActivitySession.title))
                      .where(ActivitySession.day >= since, ActivitySession.kind == "active",
                             ActivitySession.domain.is_not(None), ActivitySession.client_id.is_(None),
                             (ActivitySession.category_id.is_(None)) | (ActivitySession.club.is_not(None)))
                      .group_by(ActivitySession.domain, ActivitySession.club)).all()
    by_host: dict[str, dict] = defaultdict(lambda: {"secs": 0, "clubs": Counter(), "titles": []})
    for domain, club, secs, titles in rows:
        host = clean_host(domain)
        if not host or not is_external(host, internal, extra_public):
            continue
        h = by_host[host]
        h["secs"] += int(secs or 0)
        if club:
            h["clubs"][club] += int(secs or 0)
        h["titles"] += [t for t in titles if t][:5]
    for host, h in by_host.items():
        if h["secs"] < MIN_WEB_S or ("web_domain", host) in known:
            continue
        name = (h["clubs"].most_common(1)[0][0] if h["clubs"] else None) or \
            (namer(host, h["titles"][:5]) if namer else None) or guess_name_from_domain(host)
        c = _client_for_name(db, name)
        c.seconds_seen += h["secs"]
        if add_identifier(db, c, "web_domain", host):
            added["web_domain"] += 1
        for club in h["clubs"]:
            if norm_name(club) != norm_name(c.name) and add_identifier(db, c, "name_alias", norm_name(club)):
                added["name_alias"] += 1

    # 2. External email domains with at least two messages.
    domains: Counter = Counter()
    names: dict[str, Counter] = defaultdict(Counter)
    for meta, in db.execute(select(WorkAction.meta).where(WorkAction.source == "gmail", WorkAction.day >= since)):
        for field in ("from", "to", "cc"):
            for p in meta.get(field, []) or []:
                if not isinstance(p, dict):
                    continue
                d = email_domain(p.get("email", ""))
                if is_external(d, internal, extra_public):
                    domains[d] += 1
                    if p.get("name"):
                        names[d][p["name"]] += 1
    for d, n in domains.items():
        if n < MIN_EMAILS or ("email_domain", d) in known:
            continue
        web = db.scalar(select(ClientIdentifier).where(ClientIdentifier.kind == "web_domain", ClientIdentifier.value == d))
        c = db.get(Client, web.client_id) if web else _client_for_name(
            db, (namer(d, [x for x, _ in names[d].most_common(5)]) if namer else None) or guess_name_from_domain(d))
        if add_identifier(db, c, "email_domain", d):
            added["email_domain"] += 1

    # 3. Mantis projects.
    for project, in db.execute(select(Ticket.project).where(Ticket.project.is_not(None)).distinct()):
        if ("mantis_project", project.lower()) in known:
            continue
        c = _client_for_name(db, project)
        if add_identifier(db, c, "mantis_project", project):
            added["mantis_project"] += 1
    db.commit()
    return dict(added)


def import_names(db: Session, lines: list[str]) -> dict:
    """Admin import (e.g. the MantisClubs list): 'Club Name' or 'Club Name, domain1, domain2' per line.
    Imported clubs are confirmed straight away."""
    before = db.scalar(select(func.count()).select_from(Client))
    updated = 0
    for line in lines:
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        c = _client_for_name(db, parts[0])
        c.status = "confirmed"
        for extra in parts[1:]:
            kind = "email_address" if "@" in extra else "web_domain"
            if add_identifier(db, c, kind, clean_host(extra) if kind == "web_domain" else extra, source="import"):
                updated += 1
    db.commit()
    created = db.scalar(select(func.count()).select_from(Client)) - before
    return {"clubs": len([line for line in lines if line.strip()]), "new": created, "identifiers": updated}


def recent(days: int = 7) -> date:
    return date.today() - timedelta(days=days)
