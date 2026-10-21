from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, actor_id: int | None, action: str, target: str | None = None, meta: dict | None = None) -> None:
    """Adds an audit row to the caller's transaction; the caller commits."""
    db.add(AuditLog(actor_id=actor_id, action=action, target=target, meta=meta or {}))
