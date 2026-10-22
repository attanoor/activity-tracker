"""Domain helpers for client detection."""

import re

PUBLIC_EMAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com", "ymail.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.net", "yandex.com",
    "zoho.com", "zohomail.com", "mail.com", "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "bellsouth.net",
}
# Second-level suffixes where the registrable domain has three labels (club.co.uk).
MULTI_PART = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "com.pk", "org.pk",
              "co.in", "com.sg", "com.my", "co.za", "com.br", "com.mx", "co.jp", "com.ar", "com.tr"}


def clean_host(host: str | None) -> str | None:
    if not host:
        return None
    host = host.strip().lower().rstrip(".")
    host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def parents(host: str) -> list[str]:
    """riverclub.example.com -> [riverclub.example.com, example.com]; never the bare TLD."""
    host = clean_host(host) or ""
    parts = host.split(".")
    stop = len(registrable(host).split("."))
    return [".".join(parts[i:]) for i in range(0, len(parts) - stop + 1)]


def email_domain(address: str) -> str | None:
    if "@" not in (address or ""):
        return None
    return clean_host(address.rsplit("@", 1)[1])


def is_external(domain: str | None, internal: set[str], extra_public: set[str] = frozenset()) -> bool:
    """True when an email domain can identify a client (not ours, not a public mailbox provider)."""
    if not domain:
        return False
    d = registrable(domain)
    return d not in internal and domain not in internal and d not in PUBLIC_EMAIL and d not in extra_public


_WORD = re.compile(r"[^a-z0-9]+")


def norm_name(text: str | None) -> str:
    """'The River Club, Inc.' -> 'river club'."""
    t = _WORD.sub(" ", (text or "").lower()).strip()
    t = re.sub(r"^(the) ", "", t)
    t = re.sub(r" (inc|llc|ltd|limited|corp|co)$", "", t)
    return re.sub(r"\s+", " ", t)


def guess_name_from_domain(domain: str) -> str:
    """riverclub.com -> 'Riverclub'; river-club.co.uk -> 'River Club'. Only a starting point for the admin."""
    label = registrable(domain).split(".")[0]
    words = re.split(r"[-_]+", label)
    return " ".join(w.capitalize() for w in words if w)
