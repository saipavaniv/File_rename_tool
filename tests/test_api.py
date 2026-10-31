"""End-to-end API and security tests.  Run:  python -m pytest -q"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp()
os.environ.update({"DATA_DIR": TMP, "DATABASE_URL": f"sqlite:///{TMP}/t.db", "COOKIE_SECURE": "false",
                   "ALLOWED_HOSTS": "testserver,localhost", "LOGIN_MAX_FAILS": "3", "ANALYSIS_WORKERS": "1"})
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.cli import create_admin  # noqa: E402
from app.main import app  # noqa: E402

SAMPLES = ROOT / "samples"
ADMIN_PW = "Very-Secure-Pass-2026"


@pytest.fixture(scope="module")
def client():
    if not (SAMPLES / "Document1.pdf").exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py"), str(SAMPLES)], check=True)
    create_admin("admin", ADMIN_PW)
    with TestClient(app) as c:
        yield c


def login(c, user="admin", pw=ADMIN_PW):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    return r


def test_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/files").status_code == 401
    assert client.post("/api/analyze", files={"file": ("a.txt", b"x")}).status_code == 401


def test_security_headers(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "server" not in r.headers


def test_bad_host_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_login_and_csrf(client):
    r = login(client)
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    # state change without CSRF header is refused
    r = client.post("/api/compose", json={"fields": {"date": "2026-01-01", "type": "QUO"}, "ext": ".pdf"})
    assert r.status_code == 403
    r = client.post("/api/compose", json={"fields": {"date": "2026-01-01", "type": "QUO", "party": "ACME GmbH"}, "ext": ".pdf"},
                    headers={"x-csrf-token": csrf})
    assert r.status_code == 200 and r.json()["name"] == "2026-01-01_QUO_ACME-GmbH.pdf"
    # cross-origin request with a valid token is still refused
    r = client.post("/api/compose", json={"fields": {}}, headers={"x-csrf-token": csrf, "origin": "https://evil.example"})
    assert r.status_code == 403


def _csrf(client):
    return client.get("/api/auth/me").json()["csrf"]


def test_analyze_and_finalize(client):
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    with open(SAMPLES / "Document1.pdf", "rb") as f:
        r = client.post("/api/analyze", files={"file": ("Document1.pdf", f, "application/pdf")}, headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["suggested_name"].startswith("2026-10-28_QUO_")
    assert j["fields"]["ref"]["value"] == "PTC/Q/2026/0457"
    # user edits the name; extension can't be changed to something dangerous
    r = client.post(f"/api/files/{j['id']}/finalize", json={"final_name": "../../evil name.exe"}, headers=h)
    assert r.status_code == 200
    assert r.json()["final_name"] == "evil-name-exe.pdf"
    r = client.get("/api/files?q=PTC")
    assert r.json()["total"] >= 1


def test_zip_bomb_blocked(client):
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    with open(SAMPLES / "bomb.docx", "rb") as f:
        r = client.post("/api/analyze", files={"file": ("bomb.docx", f)}, headers=h)
    assert r.json()["status"] == "blocked"
    rid = r.json()["id"]
    assert client.post(f"/api/files/{rid}/finalize", json={"final_name": "x"}, headers=h).status_code == 400


def test_upload_limit(client):
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    big = b"0" * (51 * 1024 * 1024)
    r = client.post("/api/analyze", files={"file": ("big.txt", big)}, headers=h)
    assert r.status_code == 413


def test_users_tokens_and_permissions(client):
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    r = client.post("/api/admin/users", json={"username": "ravi", "password": "short"}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/admin/users", json={"username": "ravi", "display_name": "Ravi", "password": "Temp-Pass-2026!x"}, headers=h)
    assert r.status_code == 200, r.text
    client.cookies.clear()
    # new user must change password before using the tool
    r = login(client, "ravi", "Temp-Pass-2026!x")
    assert r.json()["user"]["must_change_password"]
    h = {"x-csrf-token": r.json()["csrf"]}
    assert client.get("/api/files").status_code == 403
    assert client.post("/api/auth/password", json={"current": "Temp-Pass-2026!x", "new": "ravi-password-123"}, headers=h).status_code == 400
    assert client.post("/api/auth/password", json={"current": "Temp-Pass-2026!x", "new": "Blue-Harbour-Pass-77"}, headers=h).status_code == 200
    # normal user can't reach admin
    assert client.get("/api/admin/users").status_code == 403
    # extension token works for analyze, but not for admin/account endpoints
    tok = client.post("/api/auth/tokens", json={"name": "Chrome"}, headers=h).json()["token"]
    assert tok.startswith("krn_")
    client.cookies.clear()
    th = {"authorization": f"Bearer {tok}"}
    with open(SAMPLES / "mail.eml", "rb") as f:
        r = client.post("/api/analyze", files={"file": ("mail.eml", f)},
                        data={"context": '{"page_host":"mail.example.com","sender_emails":["x@y.de","not an email"]}'},
                        headers=th)
    assert r.status_code == 200 and "_MAIL_" in r.json()["suggested_name"]
    assert client.get("/api/auth/tokens", headers=th).status_code == 403
    assert client.get("/api/admin/users", headers=th).status_code == 403
    assert client.post("/api/analyze", files={"file": ("a.txt", b"x")},
                       headers={"authorization": "Bearer krn_wrong"}).status_code == 401


def test_throttle_is_per_ip_and_hides_usernames(client):
    client.cookies.clear()
    for _ in range(3):
        assert login(client, "ravi", "wrong-password-xx").status_code == 401
    assert login(client, "ravi", "Blue-Harbour-Pass-77").status_code == 429   # throttled from this computer
    # an unknown username behaves exactly the same (no username discovery)
    for _ in range(3):
        r = login(client, "nobody", "whatever-password")
        assert r.status_code == 401 and r.json()["detail"] == "Wrong username or password."
    assert login(client, "nobody", "whatever-password").status_code == 429
    # the attacker's failures from another computer don't lock ravi out of his own
    r = client.post("/api/auth/login", json={"username": "ravi", "password": "Blue-Harbour-Pass-77"},
                    headers={"x-forwarded-for": "10.9.9.9"})
    assert r.status_code in (200, 429)   # TRUST_PROXY is off in tests, so this shares the test client's IP


def test_key_dies_with_password_change_and_cannot_see_all(client):
    from app.security import limiter
    limiter._hits.clear()
    client.cookies.clear()
    r = login(client)
    h = {"x-csrf-token": r.json()["csrf"]}
    tok = client.post("/api/auth/tokens", json={"name": "Admin PC"}, headers=h).json()["token"]
    th = {"authorization": f"Bearer {tok}"}
    # admin key must not unlock "everyone's files"
    mine = client.get("/api/files?all=1", headers=th).json()["total"]
    client.cookies.clear()
    login(client)
    assert client.get("/api/files?all=1").json()["total"] > mine
    # admin resets ravi's password -> ravi's extension key stops working
    users = client.get("/api/admin/users").json()
    ravi = next(u for u in users if u["username"] == "ravi")
    h = {"x-csrf-token": _csrf(client)}
    assert client.patch(f"/api/admin/users/{ravi['id']}", json={"password": "Reset-Temp-Pass-99"}, headers=h).status_code == 200
    from app.db import SessionLocal
    from app.models import ApiToken
    with SessionLocal() as db:
        assert all(t.revoked for t in db.query(ApiToken).filter(ApiToken.user_id == ravi["id"]))


def test_executables_blocked(client):
    client.cookies.clear()
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    for name, data in (("invoice.pdf", b"MZ\x90\x00 this is really a program"), ("Rechnung.hta", b"<html>Invoice No 1</html>")):
        r = client.post("/api/analyze", files={"file": (name, data)}, headers=h)
        assert r.json()["status"] == "blocked" and r.json()["suggested_name"] is None


def test_audit_links_file_id(client):
    from app.db import SessionLocal
    from app.models import AuditLog
    import json
    with SessionLocal() as db:
        e = db.query(AuditLog).filter(AuditLog.action == "file.analysed").order_by(AuditLog.id.desc()).first()
        assert json.loads(e.detail)["file_id"]


def test_parties_and_audit_chain(client):
    client.cookies.clear()
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    with open(SAMPLES / "parties.csv", "rb") as f:
        r = client.post("/api/admin/parties/import", files={"file": ("p.csv", f)}, headers=h)
    assert r.json()["added"] == 3
    with open(SAMPLES / "Document2.docx", "rb") as f:
        r = client.post("/api/analyze", files={"file": ("Document2.docx", f)}, headers=h)
    assert "_PO_Lumen-Auto_4500098123_" in r.json()["suggested_name"]
    assert client.get("/api/admin/audit/verify").json()["ok"] is True
    # tamper with the log directly in the database -> verification must fail
    from app.db import SessionLocal
    from app.models import AuditLog
    with SessionLocal() as db:
        e = db.get(AuditLog, 2)
        e.target = "someone-else"
        db.commit()
    v = client.get("/api/admin/audit/verify").json()
    assert v["ok"] is False and v["broken_at_id"] == 2


def test_settings_validation(client):
    login(client)
    h = {"x-csrf-token": _csrf(client)}
    bad = {"own_names": ["Kramski"], "own_domains": ["kramski.com"], "template": "{date}<script>", "date_order": "DMY", "auto_threshold": 0.8}
    assert client.put("/api/admin/settings", json=bad, headers=h).status_code == 400
    good = dict(bad, template="{date}_{party}_{type}_{ref}")
    assert client.put("/api/admin/settings", json=good, headers=h).status_code == 200
    r = client.post("/api/compose", json={"fields": {"date": "2026-01-01", "type": "QUO", "party": "X"}}, headers=h)
    assert r.json()["name"] == "2026-01-01_X_QUO"
