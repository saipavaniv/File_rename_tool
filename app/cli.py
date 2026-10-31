"""Admin command line.

  python -m app.cli create-admin --username admin
  python -m app.cli import-parties customers.csv
  python -m app.cli verify-audit
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import audit
from .db import SessionLocal, init_db
from .models import User
from .security import hash_password, password_problems


def create_admin(username: str, password: str | None):
    init_db()
    username = username.lower()
    if password is None:
        password = getpass.getpass("New admin password (min 12 chars): ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
    problem = password_problems(password, username)
    if problem:
        sys.exit(problem)
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if u:
            u.password_hash, u.role, u.is_active, u.locked_until, u.failed_logins = hash_password(password), "admin", True, None, 0
            u.must_change_password = False
            action = "admin.reset_cli"
        else:
            u = User(username=username, display_name=username, role="admin",
                     password_hash=hash_password(password), must_change_password=False)
            db.add(u)
            action = "admin.created_cli"
        db.flush()
        audit.log(db, action, u, target=username, ip="cli")
    print(f"Administrator '{username}' is ready. Sign in at the web address.")


def import_parties(path: str):
    import csv
    init_db()
    from . import store
    from .api.admin import PartyIn, _upsert
    n = 0
    with open(path, encoding="utf-8-sig") as f, SessionLocal() as db:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            d = PartyIn(code=row.get("code") or row["name"][:40], name=row["name"], short_name=row.get("short_name", ""),
                        aliases=row.get("aliases", ""), domains=row.get("domains", ""),
                        kind=row.get("kind") if row.get("kind") in ("customer", "supplier", "other") else "customer")
            _upsert(db, d.model_dump())
            n += 1
        audit.log(db, "parties.imported_cli", target=path, ip="cli", detail={"rows": n})
        store.invalidate()
    print(f"Imported {n} companies.")


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--username", default="admin")
    a.add_argument("--password", help="omit to be prompted (recommended)")
    b = sub.add_parser("import-parties")
    b.add_argument("csv")
    sub.add_parser("verify-audit")
    args = ap.parse_args()
    if args.cmd == "create-admin":
        create_admin(args.username, args.password)
    elif args.cmd == "import-parties":
        import_parties(args.csv)
    elif args.cmd == "verify-audit":
        init_db()
        with SessionLocal() as db:
            print(audit.verify(db))


if __name__ == "__main__":
    main()
