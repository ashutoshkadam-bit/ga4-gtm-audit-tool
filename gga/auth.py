"""Google sign-in. Two modes, chosen automatically:

LOCAL (default)  Each person runs the tool on their own computer. A browser window opens for Google sign-in
                 and the login is saved in their user folder. Uses a Desktop OAuth client (client_secret.json).

WEB              The tool is hosted on a server. People open its address and sign in with Google there.
                 Logins live only in server memory for that browser session, never on disk.
                 Turned on by setting GGA_REDIRECT_URI. Uses a Web OAuth client, configured with:
                     GGA_CLIENT_ID, GGA_CLIENT_SECRET, GGA_REDIRECT_URI   (the app's own public address)
                     GGA_ALLOWED_DOMAIN   (optional, e.g. example.com: only that Google Workspace domain may sign in)
                 Values come from environment variables or Streamlit secrets.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
APP_DIR = Path(os.environ.get("GGA_HOME", Path.home() / ".ga-gtm-audit"))
TOKEN_FILE = APP_DIR / "token.json"
TOOL_DIR = Path(__file__).resolve().parent.parent
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _cfg(name, default=""):
    """Reads a setting from the environment, then from Streamlit secrets."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001  (no secrets file)
        return default


def is_web():
    return bool(_cfg("GGA_REDIRECT_URI"))


# ================================================================== LOCAL mode
def client_secret_path():
    """Looks for the shared OAuth client file: $GGA_CLIENT_SECRET, ./client_secret.json, or ~/.ga-gtm-audit/."""
    for p in (os.environ.get("GGA_CLIENT_SECRET"), TOOL_DIR / "client_secret.json", APP_DIR / "client_secret.json"):
        if p and Path(p).exists():
            return Path(p)
    return None


def load_credentials():
    """Returns saved credentials (refreshing them if needed), or None when the user is not signed in."""
    if os.environ.get("GGA_USE_ADC"):  # developer shortcut: use gcloud application-default credentials
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES[:2])
        proj = os.environ["GGA_USE_ADC"]
        return creds.with_quota_project(proj) if len(proj) > 1 else creds  # set GGA_USE_ADC=<project id>
    if not TOKEN_FILE.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save(creds)
        return creds if creds.valid else None
    except Exception:  # noqa: BLE001  (revoked or expired token: ask the user to sign in again)
        return None


def _save(creds):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def sign_in():
    """LOCAL mode: opens the browser for Google sign-in and stores the token. Blocks until the user finishes."""
    secret = client_secret_path()
    if not secret:
        raise FileNotFoundError("client_secret.json not found. Ask your admin for it (see SETUP_ADMIN.md).")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline",
                                  success_message="Signed in. You can close this tab and return to the audit tool.")
    _save(creds)
    return creds


def sign_out():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


# ================================================================== WEB mode
def web_configured():
    return all(_cfg(k) for k in ("GGA_CLIENT_ID", "GGA_CLIENT_SECRET", "GGA_REDIRECT_URI"))


def _flow():
    redirect = _cfg("GGA_REDIRECT_URI")
    if redirect.startswith("http://localhost") or redirect.startswith("http://127.0.0.1"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # allow plain http for local testing only
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    cfg = {"web": {"client_id": _cfg("GGA_CLIENT_ID"), "client_secret": _cfg("GGA_CLIENT_SECRET"),
                   "auth_uri": AUTH_URI, "token_uri": TOKEN_URI, "redirect_uris": [redirect]}}
    return Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=redirect, autogenerate_code_verifier=False)


def _sign(payload):
    key = _cfg("GGA_CLIENT_SECRET").encode()
    return base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_state():
    """A signed, time-limited token. It lets the server accept the Google redirect without keeping any session data."""
    payload = f"{int(time.time())}.{secrets.token_urlsafe(12)}"
    return f"{payload}.{_sign(payload)}"


def check_state(state, max_age=900):
    try:
        ts, nonce, sig = state.split(".")
        ok = hmac.compare_digest(sig, _sign(f"{ts}.{nonce}"))
        return ok and 0 <= time.time() - int(ts) <= max_age
    except Exception:  # noqa: BLE001
        return False


def web_login_url():
    url, _ = _flow().authorization_url(access_type="offline", prompt="consent", state=make_state(),
                                       include_granted_scopes="true")
    return url


def web_finish(code, state):
    """Exchanges the code Google sent back for credentials. Raises ValueError with a readable message on failure."""
    if not check_state(state):
        raise ValueError("The sign-in link expired or was not started here. Please click Sign in again.")
    flow = _flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    email = user_email(creds)
    domain = _cfg("GGA_ALLOWED_DOMAIN").strip().lower().lstrip("@")
    if domain and not email.lower().endswith("@" + domain):
        raise ValueError(f"This tool is limited to @{domain} accounts. You signed in as {email or 'an unknown account'}.")
    return creds


# ================================================================== both
def user_email(creds):
    try:
        r = AuthorizedSession(creds).get("https://openidconnect.googleapis.com/v1/userinfo", timeout=15)
        return r.json().get("email", "") if r.ok else ""
    except Exception:  # noqa: BLE001
        return ""
