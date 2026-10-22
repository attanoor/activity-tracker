"""Which client (club) a piece of work was for. Only confirmed clients are used for attribution.

Order (first match wins): web domain -> club name read from the page -> ticket's Mantis project ->
email participants -> meeting attendees. Our own domains and public mailbox domains never match.
"""

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_store
from app.clients.domains import clean_host, email_domain, is_external, norm_name, parents, registrable
from app.models import Client, ClientIdentifier, Ticket


class Resolver:
    def __init__(self, db: Session):
        cfg = settings_store.get(db, "clients")
        self.internal = {d.lower().strip() for d in cfg["internal_domains"] if d.strip()}
        self.public_extra = {d.lower().strip() for d in cfg["extra_public_domains"] if d.strip()}
        rows = db.execute(select(ClientIdentifier.kind, ClientIdentifier.value, Client.id, Client.name)
                          .join(Client, Client.id == ClientIdentifier.client_id)
                          .where(Client.status == "confirmed")).all()
        self.by_kind: dict[str, dict[str, int]] = {}
        for kind, value, cid, _ in rows:
            self.by_kind.setdefault(kind, {})[value.lower()] = cid
        self.names: dict[int, str] = dict(db.execute(select(Client.id, Client.name).where(Client.status == "confirmed")).all())
        aliases = {norm_name(n): cid for cid, n in self.names.items()}
        aliases.update({norm_name(v): cid for v, cid in self.by_kind.get("name_alias", {}).items()})
        self.aliases = {a: cid for a, cid in aliases.items() if len(a) >= 3}
        self._db = db
        self._ticket_project: dict[str, str | None] = {}

    def name(self, client_id: int | None) -> str | None:
        return self.names.get(client_id) if client_id else None

    # --- single signals ------------------------------------------------------------------------------
    def by_host(self, host: str | None) -> int | None:
        host = clean_host(host)
        if not host:
            return None
        web = self.by_kind.get("web_domain", {})
        for h in parents(host):
            if h in web:
                return web[h]
        return None

    def by_text(self, text: str | None) -> int | None:
        """A club name in page text: exact alias, or an alias of 5+ characters found as whole words."""
        t = norm_name(text)
        if not t:
            return None
        if t in self.aliases:
            return self.aliases[t]
        best = None
        for alias, cid in self.aliases.items():
            if len(alias) >= 5 and re.search(rf"(^| ){re.escape(alias)}( |$)", t):
                if best is None or len(alias) > len(best[0]):
                    best = (alias, cid)
        return best[1] if best else None

    def by_ticket(self, ticket_id: str | None) -> int | None:
        if not ticket_id:
            return None
        if ticket_id not in self._ticket_project:
            t = self._db.get(Ticket, ticket_id.lstrip("0") or ticket_id)
            self._ticket_project[ticket_id] = t.project if t else None
        project = self._ticket_project[ticket_id]
        return self.by_project(project)

    def by_project(self, project: str | None) -> int | None:
        if not project:
            return None
        return self.by_kind.get("mantis_project", {}).get(project.lower()) or self.by_text(project)

    def by_emails(self, addresses: list[str]) -> int | None:
        """The client most of the external participants belong to."""
        votes: Counter = Counter()
        exact = self.by_kind.get("email_address", {})
        domains = self.by_kind.get("email_domain", {})
        for a in addresses:
            a = (a or "").lower().strip()
            d = email_domain(a)
            if not is_external(d, self.internal, self.public_extra):
                continue
            cid = exact.get(a) or domains.get(d) or domains.get(registrable(d)) or self.by_host(d)
            if cid:
                votes[cid] += 1
        return votes.most_common(1)[0][0] if votes else None

    def by_domains(self, domains: list[str]) -> int | None:
        return self.by_emails([f"x@{d}" for d in domains])

    # --- a session -----------------------------------------------------------------------------------
    def for_session(self, domain: str | None, club: str | None, title: str | None, ticket_id: str | None) -> int | None:
        return (self.by_host(domain) or self.by_text(club) or self.by_ticket(ticket_id)
                or (self.by_text(title) if domain else None))
