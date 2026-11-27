"""Saved audit history: store each audit's findings so runs can be listed, compared and trended.

Three places the history can live, chosen automatically:
  database   GGA_DATABASE_URL is set (PostgreSQL, for example Neon, Supabase or Cloud SQL; SQLite also works). Survives restarts and is shared
             by every user of a hosted copy, each person seeing only their own runs.
  file       No database set and the tool runs on your own computer: a SQLite file in your user folder.
  session    No database set on a hosted copy: history lives only in the visitor's browser session, so it works for comparing runs made in the
             same visit but is gone afterwards. The History page explains how to keep it.

Everything is scoped by an owner label (a one-way hash of the signed-in email), so people never see each other's runs.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, create_engine, delete, insert, select

from . import log

KINDS = {"audit": "GA4 and GTM audit", "page": "Page audit", "site": "Live site check"}
STATUSES = ("FAIL", "WARN", "ERROR", "PASS", "INFO")
DEFAULT_KEEP = 60

md = MetaData()
runs_t = Table(
    "runs", md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("owner", String(40), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("title", String(200)),
    Column("scope_text", Text),
    Column("source", String(16)),
    Column("n_entities", Integer, default=0),
    Column("n_fail", Integer, default=0), Column("n_warn", Integer, default=0), Column("n_error", Integer, default=0),
    Column("n_pass", Integer, default=0), Column("n_info", Integer, default=0),
    Column("version", String(16)),
    Column("meta", Text),
)
findings_t = Table(
    "findings", md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("runs.id"), nullable=False, index=True),
    Column("scope", String(8)), Column("account", String(300)), Column("entity", String(400)), Column("entity_id", String(120)),
    Column("check_name", String(120)), Column("status", String(8)), Column("detail", Text),
)
schedules_t = Table(
    "schedules", md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("owner", String(40), nullable=False, index=True),
    Column("email", String(200)),
    Column("name", String(120)),
    Column("frequency", String(10)),
    Column("accounts", Text),
    Column("only", String(4)),
    Column("days", Integer),
    Column("data_checks", Integer),
    Column("alert_always", Integer, default=0),
    Column("webhook_enc", Text),
    Column("notify_email", String(200)),
    Column("secret_enc", Text),
    Column("active", Integer, default=1),
    Column("created_at", DateTime(timezone=True)),
    Column("last_run_at", DateTime(timezone=True)),
    Column("last_status", String(16)),
    Column("last_message", Text),
    Column("last_run_id", Integer),
)


def owner_id(email):
    """A stable, anonymous label for a person. Without an email (developer credentials) everyone shares one label."""
    return hashlib.sha256(((email or "").lower() + "|gga-history").encode()).hexdigest()[:32] if email else "anonymous"


def normalize_url(url):
    url = (url or "").strip()
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old):]
    return url


def _counts(findings):
    c = {s: 0 for s in STATUSES}
    for f in findings:
        c[f["status"]] = c.get(f["status"], 0) + 1
    return c


def _row(f):
    return dict(scope=f.get("scope", "")[:8], account=(f.get("account") or "")[:300], entity=(f.get("entity") or "")[:400],
                entity_id=(f.get("entity_id") or "")[:120], check_name=(f.get("check") or "")[:120],
                status=(f.get("status") or "INFO")[:8], detail=(f.get("detail") or "")[:1000])


def _finding(r):
    return dict(scope=r["scope"], account=r["account"], entity=r["entity"], entity_id=r["entity_id"], check=r["check_name"],
                status=r["status"], detail=r["detail"] or "")


def _iso(dt):
    if isinstance(dt, str):
        return dt
    return (dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)).isoformat(timespec="seconds")


def _run_dict(r):
    return dict(id=r["id"], created_at=_iso(r["created_at"]), kind=r["kind"], title=r["title"] or "", scope_text=r["scope_text"] or "",
                source=r["source"] or "manual", n_entities=r["n_entities"] or 0, n_fail=r["n_fail"] or 0, n_warn=r["n_warn"] or 0,
                n_error=r["n_error"] or 0, n_pass=r["n_pass"] or 0, n_info=r["n_info"] or 0, version=r["version"] or "",
                meta=json.loads(r["meta"]) if r["meta"] else {})


class Store:
    """History in a SQL database (SQLite or PostgreSQL)."""

    def __init__(self, url, keep=DEFAULT_KEEP):
        self.url = normalize_url(url)
        self.keep = keep
        self.is_sqlite = self.url.startswith("sqlite")
        kw = {"connect_args": {"check_same_thread": False}} if self.is_sqlite else {"pool_pre_ping": True, "pool_size": 3, "max_overflow": 2, "connect_args": {"connect_timeout": 5}}
        self.engine = create_engine(self.url, **kw)
        md.create_all(self.engine)
        self.mode = "file" if self.is_sqlite else "database"

    def describe(self):
        if self.is_sqlite:
            return "a file on this computer" if self.url != "sqlite://" else "temporary memory"
        return "your database"

    def save_run(self, owner, kind, title, scope_text, findings, meta=None, source="manual", version=""):
        c = _counts(findings)
        ents = {(f.get("scope"), f.get("account"), f.get("entity_id") or f.get("entity")) for f in findings}
        with self.engine.begin() as conn:
            res = conn.execute(insert(runs_t).values(
                owner=owner, created_at=datetime.datetime.now(datetime.timezone.utc), kind=kind, title=(title or "")[:200],
                scope_text=scope_text or "", source=source, n_entities=len(ents), n_fail=c["FAIL"], n_warn=c["WARN"], n_error=c["ERROR"],
                n_pass=c["PASS"], n_info=c["INFO"], version=version, meta=json.dumps(meta or {})))
            run_id = res.inserted_primary_key[0]
            rows = [dict(_row(f), run_id=run_id) for f in findings]
            for i in range(0, len(rows), 1000):
                conn.execute(insert(findings_t), rows[i:i + 1000])
        self.prune(owner)
        return run_id

    def list_runs(self, owner, kind=None, limit=200):
        q = select(runs_t).where(runs_t.c.owner == owner).order_by(runs_t.c.created_at.desc(), runs_t.c.id.desc()).limit(limit)
        if kind:
            q = q.where(runs_t.c.kind == kind)
        with self.engine.connect() as conn:
            return [_run_dict(r._mapping) for r in conn.execute(q)]

    def get_run(self, owner, run_id):
        with self.engine.connect() as conn:
            r = conn.execute(select(runs_t).where(runs_t.c.owner == owner, runs_t.c.id == run_id)).first()
        return _run_dict(r._mapping) if r else None

    def get_findings(self, owner, run_id):
        if not self.get_run(owner, run_id):  # also enforces that the run belongs to this owner
            return []
        with self.engine.connect() as conn:
            return [_finding(r._mapping) for r in conn.execute(select(findings_t).where(findings_t.c.run_id == run_id).order_by(findings_t.c.id))]

    def delete_run(self, owner, run_id):
        if not self.get_run(owner, run_id):
            return False
        with self.engine.begin() as conn:
            conn.execute(delete(findings_t).where(findings_t.c.run_id == run_id))
            conn.execute(delete(runs_t).where(runs_t.c.id == run_id, runs_t.c.owner == owner))
        return True

    def delete_all(self, owner):
        ids = [r["id"] for r in self.list_runs(owner, limit=100000)]
        for i in ids:
            self.delete_run(owner, i)
        return len(ids)

    def prune(self, owner):
        old = [r["id"] for r in self.list_runs(owner, limit=100000)][self.keep:]
        for i in old:
            self.delete_run(owner, i)
        if old:
            log.event("history_pruned", removed=len(old))
        return len(old)


class SessionStore:
    """History kept only in the visitor's session (a mapping such as st.session_state). Same methods as Store."""

    mode = "session"

    def __init__(self, session, keep=20):
        self.s = session
        self.keep = keep
        self.s.setdefault("_history_runs", [])
        self.s.setdefault("_history_next", 1)

    def describe(self):
        return "this browser session only"

    def save_run(self, owner, kind, title, scope_text, findings, meta=None, source="manual", version=""):
        c = _counts(findings)
        ents = {(f.get("scope"), f.get("account"), f.get("entity_id") or f.get("entity")) for f in findings}
        rid = self.s["_history_next"]
        self.s["_history_next"] = rid + 1
        run = dict(id=rid, created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), kind=kind, title=title or "",
                   scope_text=scope_text or "", source=source, n_entities=len(ents), n_fail=c["FAIL"], n_warn=c["WARN"], n_error=c["ERROR"],
                   n_pass=c["PASS"], n_info=c["INFO"], version=version, meta=meta or {})
        self.s["_history_runs"].insert(0, dict(run, _findings=[dict(f) for f in findings]))
        del self.s["_history_runs"][self.keep:]
        return rid

    def _all(self):
        return self.s["_history_runs"]

    def list_runs(self, owner, kind=None, limit=200):
        return [{k: v for k, v in r.items() if k != "_findings"} for r in self._all() if not kind or r["kind"] == kind][:limit]

    def get_run(self, owner, run_id):
        r = next((r for r in self._all() if r["id"] == run_id), None)
        return {k: v for k, v in r.items() if k != "_findings"} if r else None

    def get_findings(self, owner, run_id):
        r = next((r for r in self._all() if r["id"] == run_id), None)
        return [dict(f) for f in r["_findings"]] if r else []

    def delete_run(self, owner, run_id):
        before = len(self._all())
        self.s["_history_runs"] = [r for r in self._all() if r["id"] != run_id]
        return len(self._all()) < before

    def delete_all(self, owner):
        n = len(self._all())
        self.s["_history_runs"] = []
        return n

    def prune(self, owner):
        return 0


def default_sqlite_url():
    from .auth import APP_DIR
    Path(APP_DIR).mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(Path(APP_DIR) / "history.db").replace("\\", "/")


def open_store(session, web, url=""):
    """Returns (store, note). note explains a fallback in plain words, or is empty."""
    url = (url or "").strip()
    keep = int(os.environ.get("GGA_HISTORY_KEEP", DEFAULT_KEEP) or DEFAULT_KEEP)
    try:
        if url:
            return Store(url, keep), ""
        if not web:
            return Store(default_sqlite_url(), keep), ""
    except Exception as e:  # noqa: BLE001
        log.exception("history_store_failed", e)
        return SessionStore(session if session is not None else {}), "The history database could not be opened, so history is kept for this session only."
    return SessionStore(session if session is not None else {}), ""
