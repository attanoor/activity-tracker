"""Agent settings in %LOCALAPPDATA%\\ActivityTracker. The device token lives in Windows Credential Manager."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ActivityTracker"
CONFIG_FILE = APP_DIR / "config.json"
QUEUE_FILE = APP_DIR / "outbox.db"
LOG_FILE = APP_DIR / "agent.log"
KEYRING_SERVICE = "ActivityTracker"
KEYRING_USER = "device_token"
LOCAL_PORT = 47823

try:  # written by scripts/build-agent.ps1 so a downloaded agent already knows its server
    from tracker_agent._build import DEFAULT_SERVER  # type: ignore
except ImportError:
    DEFAULT_SERVER = "http://localhost:3030"


@dataclass
class Config:
    server: str = DEFAULT_SERVER  # the web address; the API is under /api
    device_id: int | None = None
    idle_threshold_s: int = 300
    private: bool = False
    paused_until: str | None = None  # ISO time
    domain_only: list[str] = field(default_factory=list)

    @property
    def api(self) -> str:
        return self.server.rstrip("/") + "/api"

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def get_token() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)


def set_token(token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)


def clear_token() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass
