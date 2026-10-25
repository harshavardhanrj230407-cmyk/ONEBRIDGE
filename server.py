from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DB_PATH = Path(os.environ.get("ONEBRIDGE_DATABASE", ROOT / "data" / "onebridge.sqlite3"))
SESSION_HOURS = max(1, int(os.environ.get("ONEBRIDGE_SESSION_HOURS", "12")))
SECURE_COOKIE = os.environ.get("ONEBRIDGE_SECURE_COOKIE", "").lower() in {"1", "true", "yes"}
MAX_BODY = 1_000_000
MAX_REPORTS_PER_HOUR = 8
ROLES = {"citizen", "resolver", "organization_admin", "platform_admin"}
CATEGORIES = {
    "Roads & sidewalks",
    "Water & drainage",
    "Waste & sanitation",
    "Street lighting",
    "Accessibility",
    "Public transport",
    "Environment & safety",
    "Other",
}
STATUSES = {
    "AWAITING_VERIFICATION",
    "ADDITIONAL_EVIDENCE_REQUIRED",
    "UNDER_HUMAN_REVIEW",
    "SUPPORTED_BY_EVIDENCE",
    "ASSIGNED",
    "IN_PROGRESS",
    "RESOLUTION_SUBMITTED",
    "RESOLVED",
    "REJECTED_AFTER_REVIEW",
    "DISPUTED",
    "REOPENED",
}
STATUS_LABELS = {
    "AWAITING_VERIFICATION": "Awaiting verification",
    "ADDITIONAL_EVIDENCE_REQUIRED": "Additional evidence required",
    "UNDER_HUMAN_REVIEW": "Under human review",
    "SUPPORTED_BY_EVIDENCE": "Supported by evidence",
    "ASSIGNED": "Assigned",
    "IN_PROGRESS": "In progress",
    "RESOLUTION_SUBMITTED": "Resolution submitted",
    "RESOLVED": "Resolved",
    "REJECTED_AFTER_REVIEW": "Rejected after review",
    "DISPUTED": "Disputed",
    "REOPENED": "Reopened",
}
rate_lock = threading.Lock()
auth_attempts: dict[str, list[float]] = {}


def server_address() -> tuple[str, int]:
    port = int(os.environ.get("ONEBRIDGE_PORT", os.environ.get("PORT", "8000")))
    host = os.environ.get("ONEBRIDGE_HOST")
    if host is None:
        host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    return host, port


def session_cookie(value: str, max_age: int) -> str:
    cookie = f"onebridge_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
    if SECURE_COOKIE:
        cookie += "; Secure"
    return cookie


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


@contextmanager
def database():
    db = connect()
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db() -> None:
    with database() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('citizen','resolver','organization_admin','platform_admin')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                coordinates_shared INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'Standard',
                status TEXT NOT NULL,
                assigned_to INTEGER REFERENCES users(id),
                evidence_note TEXT NOT NULL DEFAULT '',
                resolution_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                actor_id INTEGER REFERENCES users(id),
                event_type TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                report_id INTEGER REFERENCES reports(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER REFERENCES users(id),
                action TEXT NOT NULL,
                report_id INTEGER REFERENCES reports(id),
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_assigned ON reports(assigned_to, status);
            CREATE INDEX IF NOT EXISTS idx_events_report ON report_events(report_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at);
            """
        )
        report_columns = {row["name"] for row in db.execute("PRAGMA table_info(reports)")}
        if "coordinates_shared" not in report_columns:
            db.execute("ALTER TABLE reports ADD COLUMN coordinates_shared INTEGER NOT NULL DEFAULT 0")
            if "privacy_public" in report_columns:
                db.execute("UPDATE reports SET coordinates_shared=privacy_public")
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${hashed.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = encoded.split("$", 2)
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}


def record_event(db: sqlite3.Connection, report_id: int, actor_id: int | None, event_type: str, note: str) -> None:
    db.execute(
        "INSERT INTO report_events (report_id,actor_id,event_type,note,created_at) VALUES (?,?,?,?,?)",
        (report_id, actor_id, event_type, note, now()),
    )


def notify(db: sqlite3.Connection, user_id: int, report_id: int, message: str) -> None:
    db.execute(
        "INSERT INTO notifications (user_id,report_id,message,created_at) VALUES (?,?,?,?)",
        (user_id, report_id, message, now()),
    )


def seed_demo() -> None:
    users = [
        ("Asha Demo", "citizen@onebridge.local", "CitizenDemo!2026", "citizen"),
        ("Resolver Demo", "resolver@onebridge.local", "ResolverDemo!2026", "resolver"),
        ("Admin Demo", "admin@onebridge.local", "AdminDemo!2026", "platform_admin"),
    ]
    with database() as db:
        for name, email, password, role in users:
            db.execute(
                "INSERT OR IGNORE INTO users (name,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                (name, email, password_hash(password), role, now()),
            )
        if db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0:
            citizen_id = db.execute("SELECT id FROM users WHERE email=?", (users[0][1],)).fetchone()[0]
            examples = [
                ("Water leak near the library", "Water & drainage", "A steady leak is pooling beside the library entrance.", "North campus, library entrance", "SUPPORTED_BY_EVIDENCE", "High"),
                ("Streetlight out on Cedar Lane", "Street lighting", "The light by the pedestrian crossing has been off for several evenings.", "Cedar Lane crossing", "IN_PROGRESS", "Standard"),
                ("Pothole near the bus stop", "Roads & sidewalks", "A pothole is making the curbside difficult for cyclists.", "West gate bus stop", "AWAITING_VERIFICATION", "Standard"),
            ]
            for title, category, description, location, status, priority in examples:
                tracking = f"OB-{secrets.token_hex(4).upper()}"
                stamp = now()
                cursor = db.execute(
                    """INSERT INTO reports
                    (tracking_id,user_id,title,category,description,location,priority,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (tracking, citizen_id, title, category, description, location, priority, status, stamp, stamp),
                )
                record_event(db, cursor.lastrowid, citizen_id, "REPORTED", "Report submitted by a citizen.")
                if status != "AWAITING_VERIFICATION":
                    record_event(db, cursor.lastrowid, None, status, STATUS_LABELS[status] + ".")


class AppError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "ONEBRIDGE/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}\n")

    def send_json(self, status: int, payload: dict, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_BODY:
            raise AppError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large.")
        if length == 0:
            return {}
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise AppError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send a JSON request body.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AppError(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.") from None
        if not isinstance(value, dict):
            raise AppError(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
        return value

    def guard_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            host = self.headers.get("Host", "")
            if parsed.netloc != host or parsed.scheme not in ("http", "https"):
                raise AppError(HTTPStatus.FORBIDDEN, "Cross-origin requests are not allowed.")

    def current_user(self, db: sqlite3.Connection, required: bool = True) -> sqlite3.Row | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("onebridge_session")
        if not morsel:
            if required:
                raise AppError(HTTPStatus.UNAUTHORIZED, "Please sign in to continue.")
            return None
        token_hash = hashlib.sha256(morsel.value.encode()).hexdigest()
        row = db.execute(
            """SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
            WHERE sessions.token_hash=? AND sessions.expires_at>?""",
            (token_hash, time.time()),
        ).fetchone()
        if row is None and required:
            raise AppError(HTTPStatus.UNAUTHORIZED, "Your session has expired. Please sign in again.")
        return row

    def require_role(self, user: sqlite3.Row, *roles: str) -> None:
        if user["role"] not in roles:
            raise AppError(HTTPStatus.FORBIDDEN, "Your account does not have permission to perform this action.")

    def auth_rate_limit(self) -> None:
        key = self.client_address[0]
        cutoff = time.monotonic() - 60
        with rate_lock:
            recent = [stamp for stamp in auth_attempts.get(key, []) if stamp >= cutoff]
            if len(recent) >= 12:
                raise AppError(HTTPStatus.TOO_MANY_REQUESTS, "Too many sign-in attempts. Wait a minute and try again.")
            recent.append(time.monotonic())
            auth_attempts[key] = recent

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                with database() as db:
                    self.api_get(db, parsed.path, parse_qs(parsed.query))
            except AppError as error:
                self.send_json(error.status, {"error": error.message})
            except sqlite3.Error:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The database could not complete this request."})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        self.handle_write("POST")

    def do_PATCH(self) -> None:
        self.handle_write("PATCH")

    def handle_write(self, method: str) -> None:
        try:
            self.guard_origin()
            payload = self.read_json()
            with database() as db:
                if method == "POST":
                    self.api_post(db, urlparse(self.path).path, payload)
                else:
                    self.api_patch(db, urlparse(self.path).path, payload)
        except AppError as error:
            self.send_json(error.status, {"error": error.message})
        except sqlite3.IntegrityError as error:
            message = "That email address is already registered." if "users.email" in str(error) else "This change conflicts with existing data."
            self.send_json(HTTPStatus.CONFLICT, {"error": message})
        except sqlite3.Error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The database could not complete this request."})

    def do_DELETE(self) -> None:
        self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "This operation is not available."})

    def serve_static(self, route: str) -> None:
        if route in ("/", "/index.html"):
            route = "/index.html"
        relative = unquote(route).lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT.resolve()) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def api_get(self, db: sqlite3.Connection, route: str, query: dict) -> None:
        if route == "/api/health":
            self.send_json(200, {"status": "ok", "mode": "local-demo", "ai_provider": "rules-based-only"})
            return
        if route == "/api/me":
            user = self.current_user(db, required=False)
            self.send_json(200, {"user": public_user(user) if user else None})
            return
        user = self.current_user(db)
        if route == "/api/reports":
            statuses = query.get("status", [])
            category = query.get("category", [None])[0]
            search = query.get("q", [None])[0]
            sql = """SELECT reports.*, users.name AS reporter_name,
                assigned.name AS resolver_name FROM reports
                JOIN users ON users.id=reports.user_id
                LEFT JOIN users assigned ON assigned.id=reports.assigned_to"""
            conditions: list[str] = []
            params: list = []
            if user["role"] == "citizen":
                conditions.append("reports.user_id=?")
                params.append(user["id"])
            elif user["role"] == "resolver":
                conditions.append("(reports.assigned_to=? OR reports.assigned_to IS NULL)")
                params.append(user["id"])
            statuses = [status for status in statuses if status in STATUSES]
            if statuses:
                conditions.append("reports.status IN (" + ",".join("?" for _ in statuses) + ")")
                params.extend(statuses)
            if category and category in CATEGORIES:
                conditions.append("reports.category=?")
                params.append(category)
            if search:
                conditions.append("(reports.title LIKE ? OR reports.tracking_id LIKE ? OR reports.location LIKE ?)")
                params.extend([f"%{search[:80]}%"] * 3)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY reports.created_at DESC LIMIT 200"
            rows = db.execute(sql, params).fetchall()
            self.send_json(200, {"reports": [self.report_json(row, user) for row in rows]})
            return
        if route == "/api/notifications":
            rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
            self.send_json(200, {"notifications": [dict(row) for row in rows]})
            return
        if route == "/api/demo/resolver":
            self.require_role(user, "organization_admin", "platform_admin")
            resolver = db.execute("SELECT id FROM users WHERE role='resolver' ORDER BY id LIMIT 1").fetchone()
            if resolver is None:
                raise AppError(HTTPStatus.SERVICE_UNAVAILABLE, "No authorized resolver account is available.")
            self.send_json(200, {"id": resolver["id"]})
            return
        if route == "/api/admin/summary":
            self.require_role(user, "organization_admin", "platform_admin")
            counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) AS count FROM reports GROUP BY status")}
            category_counts = [dict(row) for row in db.execute("SELECT category,COUNT(*) AS count FROM reports GROUP BY category ORDER BY count DESC")]
            total = sum(counts.values())
            resolved = counts.get("RESOLVED", 0)
            self.send_json(200, {"total": total, "statuses": counts, "categories": category_counts, "resolution_rate": round(resolved * 100 / total) if total else 0})
            return
        match = re.fullmatch(r"/api/reports/(\d+)", route)
        if match:
            report = db.execute(
                """SELECT reports.*,users.name AS reporter_name,assigned.name AS resolver_name
                FROM reports JOIN users ON users.id=reports.user_id
                LEFT JOIN users assigned ON assigned.id=reports.assigned_to WHERE reports.id=?""",
                (int(match.group(1)),),
            ).fetchone()
            if not report or (user["role"] == "citizen" and report["user_id"] != user["id"]) or (
                user["role"] == "resolver" and report["assigned_to"] not in (None, user["id"])
            ):
                raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
            events = db.execute(
                "SELECT report_events.*,users.name AS actor_name FROM report_events LEFT JOIN users ON users.id=report_events.actor_id WHERE report_id=? ORDER BY created_at",
                (report["id"],),
            ).fetchall()
            result = self.report_json(report, user)
            result["timeline"] = [dict(event) for event in events]
            self.send_json(200, {"report": result})
            return
        raise AppError(HTTPStatus.NOT_FOUND, "API route not found.")

    @staticmethod
    def report_json(row: sqlite3.Row, user: sqlite3.Row) -> dict:
        result = dict(row)
        can_view_coordinates = row["coordinates_shared"] and (
            user["role"] in {"organization_admin", "platform_admin"}
            or (user["role"] == "citizen" and row["user_id"] == user["id"])
            or (user["role"] == "resolver" and row["assigned_to"] == user["id"])
        )
        if not can_view_coordinates:
            result["latitude"] = None
            result["longitude"] = None
        result["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
        result["trustshield"] = Handler.trustshield(row)
        return result

    @staticmethod
    def trustshield(row: sqlite3.Row) -> dict:
        signals = [
            {"label": "Description provided", "supported": len(row["description"].strip()) >= 24},
            {"label": "Category selected", "supported": row["category"] in CATEGORIES},
            {"label": "Location described", "supported": len(row["location"].strip()) >= 3},
            {"label": "Supporting evidence note", "supported": bool(row["evidence_note"].strip())},
        ]
        return {"mode": "rules-based demo", "signals": signals, "review_required": row["status"] in {"AWAITING_VERIFICATION", "UNDER_HUMAN_REVIEW", "ADDITIONAL_EVIDENCE_REQUIRED"}}

    def api_post(self, db: sqlite3.Connection, route: str, payload: dict) -> None:
        if route == "/api/auth/register":
            self.auth_rate_limit()
            name = self.clean_text(payload.get("name"), "Name", 2, 80)
            email = self.clean_text(payload.get("email"), "Email", 5, 254).lower()
            password = payload.get("password")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise AppError(HTTPStatus.BAD_REQUEST, "Enter a valid email address.")
            self.validate_password(password)
            cursor = db.execute(
                "INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                (name, email, password_hash(password), "citizen", now()),
            )
            user = db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
            self.create_session(db, user)
            return
        if route == "/api/auth/login":
            self.auth_rate_limit()
            email = str(payload.get("email", "")).strip().lower()[:254]
            password = payload.get("password")
            if not isinstance(password, str) or not password or len(password) > 128:
                raise AppError(HTTPStatus.UNAUTHORIZED, "Email or password is incorrect.")
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user or not password_matches(password, user["password_hash"]):
                raise AppError(HTTPStatus.UNAUTHORIZED, "Email or password is incorrect.")
            self.create_session(db, user)
            return
        if route == "/api/auth/logout":
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            morsel = cookie.get("onebridge_session")
            if morsel:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(morsel.value.encode()).hexdigest(),))
            self.send_json(200, {"ok": True}, {"Set-Cookie": session_cookie("", 0)})
            return
        user = self.current_user(db)
        if route == "/api/reports":
            self.require_role(user, "citizen")
            title = self.clean_text(payload.get("title"), "Title", 5, 120)
            category = payload.get("category")
            if category not in CATEGORIES:
                raise AppError(HTTPStatus.BAD_REQUEST, "Choose a supported report category.")
            description = self.clean_text(payload.get("description"), "Description", 20, 3000)
            location = self.clean_text(payload.get("location"), "Location", 3, 200)
            evidence_note = str(payload.get("evidence_note", "")).strip()[:500]
            coordinates_shared = payload.get("coordinates_shared", False)
            if not isinstance(coordinates_shared, bool):
                raise AppError(HTTPStatus.BAD_REQUEST, "Choose whether authorized report handlers may view coordinates.")
            latitude = self.optional_coordinate(payload.get("latitude"), -90, 90)
            longitude = self.optional_coordinate(payload.get("longitude"), -180, 180)
            recent = db.execute("SELECT COUNT(*) FROM reports WHERE user_id=? AND created_at>?", (user["id"], datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat())).fetchone()[0]
            if recent >= MAX_REPORTS_PER_HOUR:
                raise AppError(HTTPStatus.TOO_MANY_REQUESTS, "You have reached the report limit. Try again later.")
            tracking = f"OB-{secrets.token_hex(4).upper()}"
            stamp = now()
            cursor = db.execute(
                """INSERT INTO reports (tracking_id,user_id,title,category,description,location,latitude,longitude,
                coordinates_shared,evidence_note,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tracking,user["id"],title,category,description,location,latitude,longitude,int(coordinates_shared),evidence_note,"AWAITING_VERIFICATION",stamp,stamp),
            )
            report_id = cursor.lastrowid
            record_event(db, report_id, user["id"], "REPORTED", "Report submitted and placed in the verification queue.")
            db.execute(
                "INSERT INTO audit_log (actor_id,action,report_id,detail,created_at) VALUES (?,?,?,?,?)",
                (user["id"], "report.created", report_id, "Citizen report submitted.", stamp),
            )
            admins = db.execute("SELECT id FROM users WHERE role IN ('organization_admin','platform_admin')").fetchall()
            for admin in admins:
                notify(db, admin["id"], report_id, f"New report {tracking} is awaiting review.")
            self.send_json(HTTPStatus.CREATED, {"tracking_id": tracking, "id": report_id, "status": "AWAITING_VERIFICATION"})
            return
        match = re.fullmatch(r"/api/reports/(\d+)/(review|assign|progress|resolve|confirm|dispute)", route)
        if match:
            report_id, action = int(match.group(1)), match.group(2)
            report = self.fetch_manageable_report(db, user, report_id)
            if action == "review":
                self.require_role(user, "organization_admin", "platform_admin")
                status = payload.get("status")
                if status not in {"ADDITIONAL_EVIDENCE_REQUIRED", "UNDER_HUMAN_REVIEW", "SUPPORTED_BY_EVIDENCE", "REJECTED_AFTER_REVIEW"}:
                    raise AppError(HTTPStatus.BAD_REQUEST, "Choose a valid human review outcome.")
                note = self.clean_text(payload.get("note"), "Review note", 3, 500)
                db.execute("UPDATE reports SET status=?,updated_at=? WHERE id=?", (status,now(),report_id))
                record_event(db, report_id, user["id"], status, note)
                notify(db, report["user_id"], report_id, f"Report {report['tracking_id']}: {STATUS_LABELS[status]}.")
                self.audit(db, user, "report.reviewed", report_id, status)
            elif action == "assign":
                self.require_role(user, "organization_admin", "platform_admin")
                resolver_id = payload.get("resolver_id")
                resolver = db.execute("SELECT id,name FROM users WHERE id=? AND role='resolver'", (resolver_id,)).fetchone()
                if not resolver:
                    raise AppError(HTTPStatus.BAD_REQUEST, "Choose an existing authorized resolver.")
                if report["status"] not in {"SUPPORTED_BY_EVIDENCE", "ASSIGNED", "IN_PROGRESS", "REOPENED"}:
                    raise AppError(HTTPStatus.CONFLICT, "A report must be supported by a reviewer before assignment.")
                db.execute("UPDATE reports SET assigned_to=?,status='ASSIGNED',updated_at=? WHERE id=?", (resolver_id,now(),report_id))
                note = f"Assigned to {resolver['name']}. External authority referral is not enabled."
                record_event(db, report_id, user["id"], "ASSIGNED", note)
                notify(db, report["user_id"], report_id, f"Report {report['tracking_id']} was assigned to a resolver.")
                notify(db, resolver_id, report_id, f"Report {report['tracking_id']} was assigned to you.")
                self.audit(db, user, "report.assigned", report_id, f"resolver_id={resolver_id}")
            elif action == "progress":
                self.require_role(user, "resolver", "organization_admin", "platform_admin")
                if report["assigned_to"] != user["id"] and user["role"] == "resolver":
                    raise AppError(HTTPStatus.FORBIDDEN, "This report is assigned to another resolver.")
                if report["status"] not in {"ASSIGNED", "IN_PROGRESS", "REOPENED"}:
                    raise AppError(HTTPStatus.CONFLICT, "Only assigned reports can receive progress updates.")
                note = self.clean_text(payload.get("note"), "Progress update", 3, 500)
                db.execute("UPDATE reports SET status='IN_PROGRESS',updated_at=? WHERE id=?", (now(),report_id))
                record_event(db, report_id, user["id"], "IN_PROGRESS", note)
                notify(db, report["user_id"], report_id, f"Report {report['tracking_id']} has a new progress update.")
                self.audit(db, user, "report.progress", report_id, note)
            elif action == "resolve":
                self.require_role(user, "resolver", "organization_admin", "platform_admin")
                if report["assigned_to"] != user["id"] and user["role"] == "resolver":
                    raise AppError(HTTPStatus.FORBIDDEN, "Only the assigned resolver may submit resolution.")
                if report["status"] not in {"ASSIGNED", "IN_PROGRESS", "REOPENED"}:
                    raise AppError(HTTPStatus.CONFLICT, "This report is not ready for resolution.")
                note = self.clean_text(payload.get("note"), "Resolution notes", 10, 1000)
                db.execute("UPDATE reports SET status='RESOLUTION_SUBMITTED',resolution_note=?,updated_at=? WHERE id=?", (note,now(),report_id))
                record_event(db, report_id, user["id"], "RESOLUTION_SUBMITTED", "Resolution submitted for reporter confirmation. Evidence note: " + note)
                notify(db, report["user_id"], report_id, f"Resolution for {report['tracking_id']} is ready for your confirmation.")
                self.audit(db, user, "report.resolution_submitted", report_id, "Resolution awaiting reporter confirmation.")
            elif action == "confirm":
                self.require_role(user, "citizen")
                if report["user_id"] != user["id"]:
                    raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
                if report["status"] != "RESOLUTION_SUBMITTED":
                    raise AppError(HTTPStatus.CONFLICT, "This report has no resolution awaiting confirmation.")
                db.execute("UPDATE reports SET status='RESOLVED',updated_at=? WHERE id=?", (now(),report_id))
                record_event(db, report_id, user["id"], "RESOLVED", "Reporter confirmed that the resolution addressed the problem.")
                self.audit(db, user, "report.confirmed", report_id, "Reporter confirmed resolution.")
                if report["assigned_to"]:
                    notify(db, report["assigned_to"], report_id, f"Report {report['tracking_id']} was confirmed resolved.")
            else:
                self.require_role(user, "citizen")
                if report["user_id"] != user["id"]:
                    raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
                if report["status"] != "RESOLUTION_SUBMITTED":
                    raise AppError(HTTPStatus.CONFLICT, "Only a submitted resolution can be disputed.")
                note = self.clean_text(payload.get("note"), "Dispute reason", 5, 500)
                db.execute("UPDATE reports SET status='DISPUTED',updated_at=? WHERE id=?", (now(),report_id))
                record_event(db, report_id, user["id"], "DISPUTED", note)
                notify(db, report["assigned_to"], report_id, f"Resolution for {report['tracking_id']} was disputed.")
                self.audit(db, user, "report.disputed", report_id, note)
            self.send_json(200, {"ok": True})
            return
        raise AppError(HTTPStatus.NOT_FOUND, "API route not found.")

    def api_patch(self, db: sqlite3.Connection, route: str, payload: dict) -> None:
        user = self.current_user(db)
        match = re.fullmatch(r"/api/notifications/(\d+)", route)
        if match:
            notification_id = int(match.group(1))
            cursor = db.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?", (now(),notification_id,user["id"]))
            if not cursor.rowcount:
                raise AppError(HTTPStatus.NOT_FOUND, "Notification not found.")
            self.send_json(200, {"ok": True})
            return
        raise AppError(HTTPStatus.NOT_FOUND, "API route not found.")

    def create_session(self, db: sqlite3.Connection, user: sqlite3.Row) -> None:
        raw = secrets.token_urlsafe(32)
        expiry = time.time() + SESSION_HOURS * 3600
        db.execute("INSERT INTO sessions (token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
                   (hashlib.sha256(raw.encode()).hexdigest(), user["id"], expiry, now()))
        self.send_json(200, {"user": public_user(user)}, {
            "Set-Cookie": session_cookie(raw, SESSION_HOURS * 3600)
        })

    @staticmethod
    def clean_text(value, label: str, minimum: int, maximum: int) -> str:
        if not isinstance(value, str):
            raise AppError(HTTPStatus.BAD_REQUEST, f"{label} is required.")
        cleaned = value.strip()
        if len(cleaned) < minimum or len(cleaned) > maximum:
            raise AppError(HTTPStatus.BAD_REQUEST, f"{label} must be between {minimum} and {maximum} characters.")
        return cleaned

    @staticmethod
    def validate_password(value) -> None:
        if not isinstance(value, str) or len(value) < 10 or len(value) > 128:
            raise AppError(HTTPStatus.BAD_REQUEST, "Password must be between 10 and 128 characters.")

    @staticmethod
    def optional_coordinate(value, low: float, high: float) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise AppError(HTTPStatus.BAD_REQUEST, "Location coordinates must be numeric.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise AppError(HTTPStatus.BAD_REQUEST, "Location coordinates must be numeric.") from None
        if not low <= number <= high:
            raise AppError(HTTPStatus.BAD_REQUEST, "Location coordinate is out of range.")
        return number

    def fetch_manageable_report(self, db: sqlite3.Connection, user: sqlite3.Row, report_id: int) -> sqlite3.Row:
        report = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
        if user["role"] == "citizen" and report["user_id"] != user["id"]:
            raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
        if user["role"] == "resolver" and report["assigned_to"] not in (None, user["id"]):
            raise AppError(HTTPStatus.NOT_FOUND, "Report not found.")
        return report

    @staticmethod
    def audit(db: sqlite3.Connection, user: sqlite3.Row, action: str, report_id: int, detail: str) -> None:
        db.execute("INSERT INTO audit_log (actor_id,action,report_id,detail,created_at) VALUES (?,?,?,?,?)",
                   (user["id"], action, report_id, detail, now()))


def main() -> None:
    init_db()
    if "--seed-demo" in sys.argv:
        seed_demo()
        print(f"Demo accounts and fictional sample reports are ready in {DB_PATH}")
        print("Citizen: citizen@onebridge.local / CitizenDemo!2026")
        print("Resolver: resolver@onebridge.local / ResolverDemo!2026")
        print("Admin: admin@onebridge.local / AdminDemo!2026")
        return
    host, port = server_address()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ONEBRIDGE local demo running at http://{host}:{port}")
    print("Press Ctrl+C to stop. This demo uses SQLite and rules-based TrustShield signals.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ONEBRIDGE.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
