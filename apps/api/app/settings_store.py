"""Admin-editable settings, stored per section in the `settings` table.

Secret fields are encrypted with a Fernet key in .local/secrets/app.key (created on first use, never committed)
and are never returned by the API: the admin sees only whether each one is set.
"""

import copy
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import ROOT
from app.models import Setting

KEY_FILE = ROOT / ".local" / "secrets" / "app.key"

DEFAULTS: dict[str, dict] = {
    "ai": {"enabled": True, "ollama_url": "http://127.0.0.1:11434", "model": "mistral-nemo:12b", "timeout_s": 300},
    "email": {"enabled": False, "host": "", "port": 587, "starttls": True, "username": "", "from_addr": "",
              "send_time": "19:00", "send_unreviewed": True, "attach_excel": True, "attach_pdf": True},
    "google": {"mode": "off", "client_id": "", "redirect_base": "", "calendar": True, "gmail": True, "drive": True,
               "show_subjects_to_managers": False},
    "mantis": {"enabled": False, "base_url": ""},
    "tracking": {"retention_days": 30, "generate_after_shift_minutes": 15, "privacy_text": "",
                 # A day's report can be edited until this many hours after the day ends (the sheet's daily lock).
                 "edit_hours_after_day": 12},
    "clients": {"internal_domains": [], "extra_public_domains": [], "page_reading": True, "page_allowlist": []},
    "excel": {"shared_folder": "", "master_enabled": False},
}
# Plain field name in an update -> encrypted field stored.
SECRETS: dict[str, dict[str, str]] = {
    "email": {"password": "password_enc"},
    "google": {"client_secret": "client_secret_enc", "service_account_json": "service_account_enc"},
}


def _fernet() -> Fernet:
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(Fernet.generate_key())
    return Fernet(KEY_FILE.read_bytes())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def get(db: Session, section: str) -> dict:
    row = db.get(Setting, section)
    merged = copy.deepcopy(DEFAULTS.get(section, {}))
    merged.update(row.value if row else {})
    return merged


def secret(db: Session, section: str, plain_field: str) -> str | None:
    return decrypt(get(db, section).get(SECRETS[section][plain_field], ""))


def update(db: Session, section: str, changes: dict) -> dict:
    if section not in DEFAULTS:
        raise KeyError(section)
    row = db.get(Setting, section) or Setting(key=section, value={})
    value = dict(row.value or {})
    secret_map = SECRETS.get(section, {})
    for k, v in changes.items():
        if k in secret_map:
            if v:  # empty means "keep the stored secret"
                value[secret_map[k]] = encrypt(str(v))
        elif k.endswith("_enc"):
            continue  # encrypted fields are only written through their plain name
        elif k in DEFAULTS[section]:
            value[k] = v
        elif k.startswith("clear_") and k[6:] in secret_map:
            value.pop(secret_map[k[6:]], None)
    row.value = value
    db.add(row)
    db.commit()
    return public(db, section)


def public(db: Session, section: str) -> dict:
    """The section as the admin UI sees it: secrets replaced by `<name>_set` flags."""
    data = get(db, section)
    for plain, enc in SECRETS.get(section, {}).items():
        data[f"{plain}_set"] = bool(data.pop(enc, ""))
    return data


def key_file_exists() -> bool:
    return Path(KEY_FILE).exists()
