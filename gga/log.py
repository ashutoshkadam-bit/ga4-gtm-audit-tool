"""Logging, usage events and optional error reporting.

Every message goes to standard output as one JSON line, which hosts such as Cloud Run and Streamlit Cloud collect.
Secrets are never logged: field names that look like secrets are replaced, values are shortened, and people are identified only
by a short one-way hash of their email address. Set SENTRY_DSN (and install sentry-sdk) to also send errors to Sentry.
"""
import datetime
import hashlib
import json
import logging
import os
import sys

_LOGGER = logging.getLogger("gga")


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is right now, so hosts and tests that swap it still see the messages."""

    def __init__(self):
        logging.Handler.__init__(self)

    @property
    def stream(self):
        return sys.stdout
_SECRETISH = ("secret", "token", "password", "passwd", "code", "state", "key", "authorization", "cookie")
_state = {"ready": False, "sentry": False}


def _setup():
    if _state["ready"]:
        return
    _state["ready"] = True
    _LOGGER.setLevel(os.environ.get("GGA_LOG_LEVEL", "INFO").upper())
    if not _LOGGER.handlers:
        h = _StdoutHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.addHandler(h)
        _LOGGER.propagate = False
    dsn = os.environ.get("SENTRY_DSN", "")
    if dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, send_default_pii=False, release=os.environ.get("GGA_VERSION", ""))
            _state["sentry"] = True
        except Exception:  # noqa: BLE001  (optional dependency missing or bad DSN: logging still works)
            _LOGGER.warning(json.dumps({"event": "sentry_unavailable"}))


def who(email):
    """A short one-way label for a person, so usage can be counted without storing email addresses."""
    return hashlib.sha256((email or "").lower().encode()).hexdigest()[:10] if email else ""


def clean(fields):
    out = {}
    for k, v in fields.items():
        if any(s in k.lower() for s in _SECRETISH):
            out[k] = "[hidden]"
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:200]
    return out


def _emit(level, name, **fields):
    _setup()
    rec = {"t": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "level": level, "event": name, **clean(fields)}
    _LOGGER.log(getattr(logging, level), json.dumps(rec, ensure_ascii=False))
    return rec


def event(name, **fields):
    """A usage or status event, for example event('audit_run', ga4=12, gtm=40)."""
    return _emit("INFO", name, **fields)


def warning(name, **fields):
    return _emit("WARNING", name, **fields)


def exception(name, exc, **fields):
    """Records an error with its type and message (never the stack contents of user input) and sends it to Sentry when configured."""
    rec = _emit("ERROR", name, error_type=type(exc).__name__, error=str(exc), **fields)
    if _state["sentry"]:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except Exception:  # noqa: BLE001
            pass
    return rec
