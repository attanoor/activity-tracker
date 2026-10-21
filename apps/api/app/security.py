import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Tokens and codes are stored only as SHA-256; they are high-entropy, so no salt is needed."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_enrol_code() -> str:
    # Short enough to type on the agent's first-run screen: XXXX-XXXX-XXXX without look-alike characters.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))
