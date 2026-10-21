"""Google access tokens, two ways (chosen in Admin → Integrations):

- service_account: Google Workspace domain-wide delegation. One service-account key; the app acts as each
  person (by their work email) with read-only scopes. Nobody has to click "connect".
- oauth: each person connects their own Google account once from the Account page. Google only allows
  https (or localhost) redirect addresses, so this needs the site on https.
"""

import base64
import json
import time
import urllib.parse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy.orm import Session

from app import settings_store
from app.models import GoogleToken, User

SCOPES = {
    "calendar": "https://www.googleapis.com/auth/calendar.readonly",
    "gmail": "https://www.googleapis.com/auth/gmail.metadata",
    "drive": "https://www.googleapis.com/auth/drive.activity.readonly",
}
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


class GoogleNotConfigured(Exception):
    pass


def enabled_scopes(cfg: dict) -> list[str]:
    return [SCOPES[k] for k in ("calendar", "gmail", "drive") if cfg.get(k)]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def service_account_jwt(key: dict, subject: str, scopes: list[str], now: int | None = None) -> str:
    now = now or int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": key["client_email"], "sub": subject, "scope": " ".join(scopes),
              "aud": key.get("token_uri", TOKEN_URL), "iat": now, "exp": now + 3600}
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}".encode()
    private = serialization.load_pem_private_key(key["private_key"].encode(), password=None)
    sig = private.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode()}.{_b64(sig)}"


def google_identity(user: User) -> str:
    return user.google_email or user.email


def access_token(db: Session, user: User, http: httpx.Client) -> str:
    cfg = settings_store.get(db, "google")
    scopes = enabled_scopes(cfg)
    if cfg["mode"] == "service_account":
        raw = settings_store.secret(db, "google", "service_account_json")
        if not raw:
            raise GoogleNotConfigured("No service-account key uploaded")
        key = json.loads(raw)
        r = http.post(key.get("token_uri", TOKEN_URL), data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": service_account_jwt(key, google_identity(user), scopes)})
    elif cfg["mode"] == "oauth":
        tok = db.get(GoogleToken, user.id)
        secret = settings_store.secret(db, "google", "client_secret")
        if not tok or not secret or not cfg["client_id"]:
            raise GoogleNotConfigured("This person has not connected Google")
        r = http.post(TOKEN_URL, data={"grant_type": "refresh_token", "client_id": cfg["client_id"],
                                       "client_secret": secret,
                                       "refresh_token": settings_store.decrypt(tok.refresh_token_enc)})
    else:
        raise GoogleNotConfigured("Google is switched off")
    if r.status_code != 200:
        raise GoogleNotConfigured(f"Google refused the token request ({r.status_code}): {r.text[:200]}")
    return r.json()["access_token"]


def oauth_start_url(cfg: dict, state: str) -> str:
    q = {"client_id": cfg["client_id"], "redirect_uri": redirect_uri(cfg), "response_type": "code",
         "scope": " ".join(enabled_scopes(cfg) + ["openid", "email"]), "access_type": "offline",
         "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return f"{AUTH_URL}?{urllib.parse.urlencode(q)}"


def redirect_uri(cfg: dict) -> str:
    return cfg["redirect_base"].rstrip("/") + "/api/integrations/google/callback"


def oauth_exchange(db: Session, user: User, code: str, http: httpx.Client) -> GoogleToken:
    cfg = settings_store.get(db, "google")
    r = http.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": code, "client_id": cfg["client_id"],
                                   "client_secret": settings_store.secret(db, "google", "client_secret") or "",
                                   "redirect_uri": redirect_uri(cfg)})
    if r.status_code != 200:
        raise GoogleNotConfigured(f"Google refused the sign-in ({r.status_code})")
    data = r.json()
    if "refresh_token" not in data:
        raise GoogleNotConfigured("Google did not return offline access; remove the app at "
                                  "myaccount.google.com/permissions and connect again")
    payload = data.get("id_token", "..").split(".")[1]
    email = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)) or b"{}").get("email", user.email)
    tok = db.get(GoogleToken, user.id) or GoogleToken(user_id=user.id)
    tok.google_email = email
    tok.refresh_token_enc = settings_store.encrypt(data["refresh_token"])
    tok.scopes = data.get("scope", "")
    db.add(tok)
    db.commit()
    return tok
