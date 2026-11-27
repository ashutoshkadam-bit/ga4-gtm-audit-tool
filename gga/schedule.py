"""Scheduled audits: run an audit automatically (daily, weekly or monthly) and send an alert when something got worse.

How it fits together
  * A signed-in person creates a schedule on the Schedules page. The tool stores the schedule in the history database together with the
    person's Google refresh token, encrypted (Fernet) with a key only the admin holds (GGA_SCHEDULE_KEY). The token is read-only
    (Analytics and Tag Manager read access) and never shown again.
  * A runner, `python -m gga.schedule`, looks for schedules that are due, refreshes the token, runs the audit, saves the run to History
    (marked "scheduled"), compares it with the previous run and sends an alert. The repository's GitHub Actions workflow
    `scheduled-audits.yml` runs it every day; you can also run it from Windows Task Scheduler or cron.
  * The alert goes to a webhook (Slack, Microsoft Teams, Google Chat, Discord or anything that accepts JSON) and, if the admin set up
    SMTP, to an email address.

Settings: GGA_DATABASE_URL (history database), GGA_SCHEDULE_KEY (long random secret, needed on the website and on the runner),
optional GGA_SMTP_HOST, GGA_SMTP_PORT, GGA_SMTP_USER, GGA_SMTP_PASSWORD, GGA_SMTP_FROM.
"""
import base64
import collections
import datetime
import hashlib
import json
import secrets
import smtplib
import sys
from email.message import EmailMessage

import requests
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import insert, select, update, delete

from . import __version__, auth, compare, core, history, log, site

FREQUENCIES = {"daily": 1, "weekly": 7, "monthly": 30}
MAX_PER_PERSON = 5
TOLERANCE = datetime.timedelta(hours=3)  # a daily job may start a little earlier than 24 hours after the last run


class ScheduleError(Exception):
    """A message that is safe and clear to show to the user."""


# ------------------------------------------------------------------ encryption of stored secrets
def _seed():
    seed = auth._cfg("GGA_SCHEDULE_KEY") or auth._cfg("GGA_STATE_KEY") or auth._cfg("GGA_CLIENT_SECRET")  # noqa: SLF001
    if seed:
        return seed
    if auth.is_web():
        return ""  # a hosted copy must have an explicit key, so the runner can read what the website stored
    keyfile = auth.APP_DIR / "schedule.key"  # local use: make a key once and keep it in the user folder
    if not keyfile.exists():
        auth.APP_DIR.mkdir(parents=True, exist_ok=True)
        keyfile.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return keyfile.read_text(encoding="utf-8").strip()


def key_configured():
    return bool(_seed())


def _vault():
    seed = _seed()
    if not seed:
        raise ScheduleError("Scheduled audits need a secret key. The admin sets GGA_SCHEDULE_KEY (any long random text) on the website and "
                            "on the GitHub repository, then reboots the app.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("gga-schedule|" + seed).encode()).digest()))


def seal(obj):
    return _vault().encrypt(json.dumps(obj).encode()).decode()


def unseal(text):
    try:
        return json.loads(_vault().decrypt(text.encode()).decode())
    except (InvalidToken, ValueError, AttributeError):
        raise ScheduleError("The stored sign-in could not be decrypted. The secret key probably changed. Delete this schedule and create it again.")


# ------------------------------------------------------------------ storing schedules
def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def public(row):
    """A schedule as shown to people: no secrets."""
    r = dict(row)
    hook = ""
    if r.get("webhook_enc"):
        try:
            from urllib.parse import urlparse
            hook = urlparse(unseal(r["webhook_enc"])).hostname or "set"
        except ScheduleError:
            hook = "set"
    return dict(id=r["id"], name=r["name"], frequency=r["frequency"], accounts=r["accounts"] or "", only=r["only"], days=r["days"],
                data_checks=bool(r["data_checks"]), alert_always=bool(r["alert_always"]), webhook_host=hook, notify_email=r["notify_email"] or "",
                active=bool(r["active"]), last_run_at=_aware(r["last_run_at"]), last_status=r["last_status"] or "",
                last_message=r["last_message"] or "", last_run_id=r["last_run_id"], created_at=_aware(r["created_at"]), email=r["email"] or "")


def _check_webhook(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith("https://"):
        raise ScheduleError("The alert webhook must start with https://")
    try:
        site.check_public(url)
    except site.BlockedAddress as e:
        raise ScheduleError(f"That webhook address was refused: {e}.")
    return url


def create(store, owner, email, creds, name, frequency="weekly", accounts="", only="all", days=30, data_checks=True, webhook="",
           notify_email="", alert_always=False):
    if getattr(store, "mode", "session") == "session":
        raise ScheduleError("Scheduled audits need a history database. Ask the admin to set GGA_DATABASE_URL.")
    name = (name or "").strip()
    if not name:
        raise ScheduleError("Give the schedule a name.")
    if frequency not in FREQUENCIES or only not in ("all", "ga4", "gtm"):
        raise ScheduleError("Pick how often to run and what to audit.")
    rt, cid, cs = getattr(creds, "refresh_token", None), getattr(creds, "client_id", None), getattr(creds, "client_secret", None)
    if not (rt and cid and cs):
        raise ScheduleError("This sign-in cannot be reused later. Sign in with Google (or with your own OAuth client, or a refresh token plus its "
                            "client) on the Profile page first. A pasted access token expires after an hour.")
    if len(list_for(store, owner)) >= MAX_PER_PERSON:
        raise ScheduleError(f"You can have up to {MAX_PER_PERSON} schedules. Delete one first.")
    hook = _check_webhook(webhook)
    notify_email = (notify_email or "").strip()
    if notify_email and "@" not in notify_email:
        raise ScheduleError("That email address does not look right.")
    row = dict(owner=owner, email=email or "", name=name[:120], frequency=frequency, accounts=(accounts or "").strip()[:300], only=only,
               days=int(days), data_checks=int(bool(data_checks)), alert_always=int(bool(alert_always)),
               webhook_enc=seal(hook) if hook else "", notify_email=notify_email[:200],
               secret_enc=seal(dict(refresh_token=rt, client_id=cid, client_secret=cs)), active=1, created_at=_now(), last_status="new",
               last_message="Waiting for the first automatic run.")
    with store.engine.begin() as conn:
        sid = conn.execute(insert(history.schedules_t).values(**row)).inserted_primary_key[0]
    log.event("schedule_created", frequency=frequency, only=only, user=log.who(email))
    return sid


def list_for(store, owner):
    with store.engine.connect() as conn:
        rows = conn.execute(select(history.schedules_t).where(history.schedules_t.c.owner == owner).order_by(history.schedules_t.c.id))
        return [public(r._mapping) for r in rows]


def _all_active(store, only_id=None):
    q = select(history.schedules_t).where(history.schedules_t.c.active == 1)
    if only_id:
        q = q.where(history.schedules_t.c.id == only_id)
    with store.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q.order_by(history.schedules_t.c.id))]


def get_row(store, owner, sid):
    with store.engine.connect() as conn:
        r = conn.execute(select(history.schedules_t).where(history.schedules_t.c.id == sid, history.schedules_t.c.owner == owner)).first()
    return dict(r._mapping) if r else None


def set_active(store, owner, sid, active):
    with store.engine.begin() as conn:
        conn.execute(update(history.schedules_t).where(history.schedules_t.c.id == sid, history.schedules_t.c.owner == owner).values(active=int(active)))


def remove(store, owner, sid):
    with store.engine.begin() as conn:
        n = conn.execute(delete(history.schedules_t).where(history.schedules_t.c.id == sid, history.schedules_t.c.owner == owner)).rowcount
    return bool(n)


def is_due(row, now=None):
    now = now or _now()
    last = _aware(row.get("last_run_at"))
    if last is None:
        return True
    return now - last >= datetime.timedelta(days=FREQUENCIES.get(row["frequency"], 7)) - TOLERANCE


def next_run(sched):
    """When the next automatic run is due, or None when it is paused."""
    if not sched["active"]:
        return None
    last = sched["last_run_at"]
    return None if last is None else last + datetime.timedelta(days=FREQUENCIES.get(sched["frequency"], 7)) - TOLERANCE


# ------------------------------------------------------------------ running
def credentials(secret):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials(token=None, refresh_token=secret["refresh_token"], client_id=secret["client_id"], client_secret=secret["client_secret"],
                        token_uri=auth.TOKEN_URI, scopes=auth.SCOPES)
    try:
        creds.refresh(Request())
    except Exception as e:  # noqa: BLE001
        raise ScheduleError("Google no longer accepts the saved sign-in (it was revoked, expired or the app is in testing mode). "
                            f"Open the Schedules page, delete this schedule and create it again. ({str(e)[:90]})")
    return creds


def run_audit(creds, accounts="", only="all", days=30, data_checks=True, progress=None):
    """The same audit as the command line, for the accounts whose name contains any of the comma-separated words."""
    aud = core.Auditor(creds, dict(days=days, ga4_data=bool(data_checks)))
    words = [w.strip().lower() for w in (accounts or "").split(",") if w.strip()]

    def keep(name):
        return not words or any(w in name.lower() for w in words)

    ga4 = aud.list_ga4()
    gtm = aud.list_gtm()
    ga4_pick = [r for r in ga4 if keep(r["account"])] if only in ("ga4", "all") else []
    gtm_pick = [r for r in gtm if keep(r["account"])] if only in ("gtm", "all") else []
    if not ga4_pick and not gtm_pick:
        raise ScheduleError("No GA4 property or GTM container matched this schedule's account filter.")
    known = core.all_ga4_measurement_ids(aud, ga4) if gtm_pick else None
    return core.run_audit(aud, ga4_pick, gtm_pick, known, progress=progress)


def scope_text(row):
    return f"Scheduled - {row['name']} - {row['accounts'] or 'all accounts'} - {row['only']}"


def build_alert(row, run, cmp_):
    """(subject, text) describing the run, written for a chat message or an email."""
    k = cmp_["counts"] if cmp_ else None
    lines = [f"Scheduled audit \"{row['name']}\": {run['n_entities']} items, {run['n_fail']} fail, {run['n_warn']} warn, {run['n_error']} could not run."]
    if cmp_:
        lines.append(f"Since the last run: {compare.headline(cmp_)}.")
        for title, key in (("New problems", "new_problems"), ("Got worse", "worsened")):
            rows = cmp_[key][:6]
            if rows:
                lines.append(f"{title} ({k[key]}):")
                lines += [f"  - {r['entity']} ({r['account']}): {r['check']}" for r in rows]
                if k[key] > len(rows):
                    lines.append(f"  ...and {k[key] - len(rows)} more")
    else:
        lines.append("This is the first run, so there is nothing to compare with yet.")
    uri = auth.redirect_uri()
    if uri:
        lines.append(f"Details and the full comparison: {uri}")
    bad = bool(k and (k["new_problems"] or k["worsened"]))
    subject = f"[GA4/GTM audit] {row['name']}: " + ("new problems found" if bad else "no new problems")
    return subject, "\n".join(lines)


def send_webhook(url, text):
    """Posts the text in the shapes Slack, Teams, Google Chat and Discord all read. Returns an error message or ''."""
    try:
        site.check_public(url)
        r = requests.post(url, json={"text": text, "content": text}, timeout=15, allow_redirects=False)
        return "" if r.status_code < 300 else f"the webhook answered HTTP {r.status_code}"
    except site.BlockedAddress as e:
        return f"webhook refused: {e}"
    except requests.RequestException as e:
        return f"webhook not reachable ({type(e).__name__})"


def smtp_configured():
    return bool(auth._cfg("GGA_SMTP_HOST") and auth._cfg("GGA_SMTP_FROM"))  # noqa: SLF001


def send_email(to, subject, text):
    if not smtp_configured():
        return "email is not set up on this server"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = auth._cfg("GGA_SMTP_FROM"), to, subject  # noqa: SLF001
    msg.set_content(text)
    try:
        with smtplib.SMTP(auth._cfg("GGA_SMTP_HOST"), int(auth._cfg("GGA_SMTP_PORT", "587") or 587), timeout=20) as s:  # noqa: SLF001
            s.starttls()
            if auth._cfg("GGA_SMTP_USER"):  # noqa: SLF001
                s.login(auth._cfg("GGA_SMTP_USER"), auth._cfg("GGA_SMTP_PASSWORD"))  # noqa: SLF001
            s.send_message(msg)
        return ""
    except Exception as e:  # noqa: BLE001
        return f"email failed ({type(e).__name__})"


def _notify(row, subject, text):
    problems = []
    if row.get("webhook_enc"):
        err = send_webhook(unseal(row["webhook_enc"]), text)
        problems += [err] if err else []
    if row.get("notify_email"):
        err = send_email(row["notify_email"], subject, text)
        problems += [err] if err else []
    return "; ".join(problems)


def _finish(store, row, status, message, run_id=None):
    with store.engine.begin() as conn:
        conn.execute(update(history.schedules_t).where(history.schedules_t.c.id == row["id"]).values(
            last_run_at=_now(), last_status=status, last_message=message[:500], last_run_id=run_id or row.get("last_run_id")))


def run_one(store, row, audit=None, creds_fn=None, progress=None):
    """Runs one schedule now. Never raises: the outcome is stored on the schedule and returned as (status, message)."""
    audit = audit or run_audit
    creds_fn = creds_fn or credentials
    try:
        creds = creds_fn(unseal(row["secret_enc"]))
        findings, _inv = audit(creds, row["accounts"], row["only"], row["days"], bool(row["data_checks"]), progress)
        scope = scope_text(row)
        prev = next((r for r in store.list_runs(row["owner"], "audit") if r["scope_text"] == scope), None)
        old = store.get_findings(row["owner"], prev["id"]) if prev else None
        run_id = store.save_run(row["owner"], "audit", row["name"], scope, findings,
                                dict(days=row["days"], schedule=row["id"], frequency=row["frequency"]), source="scheduled", version=__version__)
        run = store.get_run(row["owner"], run_id)
        cmp_ = compare.compare(old, findings) if old is not None else None
        subject, text = build_alert(row, run, cmp_)
        worse = bool(cmp_ and (cmp_["counts"]["new_problems"] or cmp_["counts"]["worsened"]))
        sent = ""
        if worse or row["alert_always"]:
            sent = _notify(row, subject, text)
        msg = text.splitlines()[0] + (f" Alert problem: {sent}." if sent else "")
        _finish(store, row, "ok", msg, run_id)
        log.event("schedule_ran", id=row["id"], findings=len(findings), alerted=worse, user=log.who(row.get("email", "")))
        return "ok", msg
    except ScheduleError as e:
        msg = str(e)
    except Exception as e:  # noqa: BLE001
        log.exception("schedule_failed", e, id=row["id"])
        msg = f"The audit could not finish ({type(e).__name__}: {str(e)[:120]})."
    try:
        _notify(row, f"[GA4/GTM audit] {row['name']}: could not run", f"Scheduled audit \"{row['name']}\" could not run. {msg}")
    except Exception:  # noqa: BLE001
        pass
    _finish(store, row, "error", msg)
    return "error", msg


def run_due(store, now=None, only_id=None, **kw):
    """Runs every active schedule that is due (or the one named). Returns a list of (id, name, status, message)."""
    out = []
    for row in _all_active(store, only_id):
        if only_id or is_due(row, now):
            st_, msg = run_one(store, row, **kw)
            out.append((row["id"], row["name"], st_, msg))
    return out


def main():
    url = auth._cfg("GGA_DATABASE_URL")  # noqa: SLF001
    if not url:
        print("GGA_DATABASE_URL is not set, so there are no schedules to run.")
        return 0
    store = history.Store(url)
    results = run_due(store)
    counts = collections.Counter(r[2] for r in results)
    print(f"{len(results)} scheduled audits ran: {counts['ok']} ok, {counts['error']} with problems")
    for sid, name, st_, msg in results:
        print(f"  [{st_}] {name}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
