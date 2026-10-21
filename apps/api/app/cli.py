"""Admin commands:  python -m app.cli seed | create-admin <email> <name> [--password-file <path>] | demo [days] | demo-remove"""

import getpass
import secrets
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from app.seed import ensure_defaults


def main(argv: list[str]) -> int:
    if argv[:1] == ["seed"]:
        with SessionLocal() as db:
            ensure_defaults(db)
        print("default categories and rules ensured")
        return 0
    if argv[:1] == ["demo"]:
        from app import demo
        with SessionLocal() as db:
            created = demo.seed(db, int(argv[1]) if len(argv) > 1 else 7)
        print(f"demo data ready; {len(created)} new accounts" + (" (passwords in .local/secrets/demo-users.txt)" if created else ""))
        return 0
    if argv[:1] == ["e2e-setup"]:
        import json

        from app import demo
        from app.config import ROOT
        with SessionLocal() as db:
            data = demo.e2e_setup(db)
        f = ROOT / ".local" / "secrets" / "e2e.json"
        f.write_text(json.dumps(data, indent=2))
        print(f"e2e accounts ready for {data['day']} (credentials in {f})")
        return 0
    if argv[:1] == ["demo-remove"]:
        from app import demo
        with SessionLocal() as db:
            print(f"removed {demo.remove(db)} demo people and their data")
        return 0
    if argv[:1] == ["create-admin"] and len(argv) in (3, 5):
        email, name = argv[1].strip().lower(), argv[2]
        if len(argv) == 5 and argv[3] == "--password-file":
            # Generates a password and writes it only to the given file (for unattended setup).
            password = secrets.token_urlsafe(15)
        else:
            password = getpass.getpass("Password (min 10 chars): ")
        if len(password) < 10:
            print("password too short")
            return 1
        with SessionLocal() as db:
            if db.scalar(select(User).where(func.lower(User.email) == email)):
                print("user exists")
                return 1
            db.add(User(email=email, name=name, password_hash=hash_password(password), role="admin"))
            db.commit()
        if len(argv) == 5:
            Path(argv[4]).write_text(f"email: {email}\npassword: {password}\n")
            print(f"admin {email} created; password written to {argv[4]}")
            return 0
        print(f"admin {email} created")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
