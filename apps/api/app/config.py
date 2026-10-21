from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".local" / ".env", env_prefix="TRACKER_", extra="ignore")

    database_url: str = "postgresql+psycopg://tracker@127.0.0.1:5546/activity"
    session_ttl_hours: int = 12
    # Gaps shorter than this between two samples of the same activity are bridged.
    merge_gap_seconds: int = 30
    # Retention of raw events; sessions and DSRs are kept.
    raw_retention_days: int = 30
    enrol_code_ttl_days: int = 7
    cookie_secure: bool = False


settings = Settings()
