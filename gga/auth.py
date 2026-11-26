"""Google sign-in for teammates. Each person signs in with their own Google account in the browser.

No Google Cloud knowledge is needed: the tool ships with one shared OAuth client (client_secret.json) that an
admin sets up once. Each user's own login decides what they can see, and the token never leaves their machine.
"""
import json
import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
APP_DIR = Path(os.environ.get("GGA_HOME", Path.home() / ".ga-gtm-audit"))
TOKEN_FILE = APP_DIR / "token.json"
TOOL_DIR = Path(__file__).resolve().parent.parent


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
    """Opens the browser for Google sign-in and stores the token. Blocks until the user finishes."""
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


def user_email(creds):
    try:
        r = AuthorizedSession(creds).get("https://openidconnect.googleapis.com/v1/userinfo", timeout=15)
        return r.json().get("email", "") if r.ok else ""
    except Exception:  # noqa: BLE001
        return ""
