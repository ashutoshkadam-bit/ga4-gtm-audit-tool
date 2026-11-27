"""Google sign-in. Two modes, chosen automatically:

LOCAL (default)  Each person runs the tool on their own computer. A browser window opens for Google sign-in
                 and the login is saved in their user folder.

WEB              The tool is hosted on a server. People open its address and sign in there. Logins live only in
                 server memory for that browser session, never on disk. Turned on by setting GGA_REDIRECT_URI.

Three ways to connect an account, in both modes (see the Profile page):
  1. The shared sign-in the admin set up (GGA_CLIENT_ID / GGA_CLIENT_SECRET in web mode, client_secret.json locally).
  2. The person's own Google OAuth client (their client ID and secret), so quotas and test-user lists are their own.
  3. A pasted token: an access token (valid about an hour) or a refresh token with its client ID and secret.

Settings (environment variables or Streamlit secrets):
  GGA_CLIENT_ID, GGA_CLIENT_SECRET, GGA_REDIRECT_URI   shared web sign-in; the redirect is the app's own public address
  GGA_ALLOWED_DOMAIN                                    optional, e.g. example.com: only that Google Workspace domain may sign in
  GGA_STATE_KEY                                         optional secret used to protect the sign-in redirect
"""
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

from . import log

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
DATA_SCOPES = SCOPES[:2]
APP_DIR = Path(os.environ.get("GGA_HOME", Path.home() / ".ga-gtm-audit"))
TOKEN_FILE = APP_DIR / "token.json"
TOOL_DIR = Path(__file__).resolve().parent.parent
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
_PROCESS_KEY = secrets.token_hex(24)  # fallback state key: sign-in redirects work within one running server


class AuthError(Exception):
    """An error with a message that is safe and clear to show to the user."""


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


def redirect_uri():
    return _cfg("GGA_REDIRECT_URI")


# ================================================================== LOCAL mode
def client_secret_path():
    """Looks for the shared OAuth client file: $GGA_CLIENT_SECRET, ./client_secret.json, or ~/.ga-gtm-audit/."""
    for p in (os.environ.get("GGA_CLIENT_SECRET"), TOOL_DIR / "client_secret.json", APP_DIR / "client_secret.json"):
        if p and Path(p).exists() and str(p).lower().endswith(".json"):
            return Path(p)
    return None


def load_credentials():
    """Returns saved credentials (refreshing them if needed), or None when the user is not signed in."""
    if os.environ.get("GGA_USE_ADC"):  # developer shortcut: use gcloud application-default credentials
        import google.auth
        creds, _ = google.auth.default(scopes=DATA_SCOPES)
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
    """LOCAL mode, shared client file: opens the browser for Google sign-in and stores the token."""
    secret = client_secret_path()
    if not secret:
        raise AuthError("client_secret.json was not found. Ask your admin for it, or use your own OAuth client on the Profile page.")
    return _local_flow(InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES))


def sign_in_with_client(client_id, client_secret):
    """LOCAL mode, the person's own OAuth client (Desktop app type)."""
    _check_client(client_id, client_secret)
    cfg = {"installed": {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "auth_uri": AUTH_URI,
                         "token_uri": TOKEN_URI, "redirect_uris": ["http://localhost"]}}
    return _local_flow(InstalledAppFlow.from_client_config(cfg, SCOPES))


def _local_flow(flow):
    try:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline",
                                      success_message="Signed in. You can close this tab and return to the audit tool.")
    except Exception as e:  # noqa: BLE001
        raise AuthError(f"Sign-in did not complete ({str(e)[:120]}). Please try again.")
    _save(creds)
    return creds


def sign_out():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


# ================================================================== WEB mode
def shared_client():
    """The admin's shared web client, or None."""
    cid, sec = _cfg("GGA_CLIENT_ID"), _cfg("GGA_CLIENT_SECRET")
    return dict(id=cid, secret=sec) if cid and sec else None


def web_configured():
    return bool(shared_client() and redirect_uri())


def _fernet():
    seed = _cfg("GGA_STATE_KEY") or _cfg("GGA_CLIENT_SECRET") or _PROCESS_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("gga-state|" + seed).encode()).digest()))


def make_state(client=None):
    """An encrypted, time-limited token carried through the Google redirect. For a person's own client it also carries
    that client's ID and secret, so they survive the redirect without being stored anywhere."""
    payload = {"n": secrets.token_urlsafe(8)}
    if client:
        payload["c"] = {"id": client["id"], "secret": client["secret"]}
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def read_state(state, max_age=900):
    try:
        return json.loads(_fernet().decrypt(state.encode(), ttl=max_age).decode())
    except (InvalidToken, ValueError, AttributeError):
        return None


def _check_client(cid, secret):
    cid, secret = (cid or "").strip(), (secret or "").strip()
    if not cid.endswith(".apps.googleusercontent.com") or len(cid) < 30:
        raise AuthError("That does not look like a Google client ID. It should end in .apps.googleusercontent.com.")
    if len(secret) < 10:
        raise AuthError("Please enter the client secret that goes with that client ID.")


def _flow(client):
    uri = redirect_uri()
    if not uri:
        raise AuthError("This copy of the tool is not set up for web sign-in (GGA_REDIRECT_URI is missing).")
    if uri.startswith(("http://localhost", "http://127.0.0.1")):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # allow plain http for local testing only
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    cfg = {"web": {"client_id": client["id"], "client_secret": client["secret"], "auth_uri": AUTH_URI, "token_uri": TOKEN_URI,
                   "redirect_uris": [uri]}}
    return Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=uri, autogenerate_code_verifier=False)


def web_login_url(own_client=None):
    """Google sign-in address. Pass a person's own client dict(id, secret) to use it instead of the shared one."""
    client = own_client or shared_client()
    if not client:
        raise AuthError("No sign-in client is configured. Use your own OAuth client or a token on the Profile page.")
    if own_client:
        _check_client(own_client["id"], own_client["secret"])
    url, _ = _flow(client).authorization_url(access_type="offline", prompt="consent", state=make_state(own_client),
                                             include_granted_scopes="true")
    return url


def _domain_ok(email):
    domain = _cfg("GGA_ALLOWED_DOMAIN").strip().lower().lstrip("@")
    if domain and not (email or "").lower().endswith("@" + domain):
        log.warning("signin_rejected_domain", user=log.who(email))
        raise AuthError(f"This tool is limited to @{domain} accounts. You signed in as {email or 'an unknown account'}.")


def web_finish(code, state):
    """Exchanges the code Google sent back for credentials. Returns (creds, source). Raises AuthError with a readable message."""
    st = read_state(state or "")
    if st is None:
        log.warning("signin_failed", reason="state expired or not started here")
        raise AuthError("The sign-in link expired or was not started here. Please click Sign in again.")
    own = st.get("c")
    client = own or shared_client()
    if not client:
        raise AuthError("No sign-in client is configured on this server.")
    try:
        flow = _flow(client)
        flow.fetch_token(code=code)
    except AuthError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("signin_failed", e, reason="code exchange")
        raise AuthError("Google did not accept the sign-in. Check that your OAuth client allows this redirect address and "
                        f"that your account is allowed to use it. ({str(e)[:100]})")
    creds = flow.credentials
    email = user_email(creds)
    _domain_ok(email)
    log.event("signin", method="own client" if own else "shared", user=log.who(email))
    return creds, ("your own client" if own else "shared sign-in")


# ================================================================== pasted tokens
def creds_from_token(access_token="", refresh_token="", client_id="", client_secret=""):
    """Builds credentials from a pasted token and checks it works. Returns (creds, email, scopes)."""
    access_token, refresh_token = (access_token or "").strip(), (refresh_token or "").strip()
    if refresh_token:
        _check_client(client_id, client_secret)
        creds = Credentials(token=None, refresh_token=refresh_token, client_id=client_id.strip(), client_secret=client_secret.strip(),
                            token_uri=TOKEN_URI, scopes=SCOPES)
        try:
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"Google rejected that refresh token or client ({str(e)[:100]}). Check that they belong together.")
    elif access_token:
        if len(access_token) < 20:
            raise AuthError("That access token looks too short. Paste the whole token.")
        creds = Credentials(token=access_token, scopes=SCOPES)
    else:
        raise AuthError("Paste an access token, or a refresh token with its client ID and secret.")
    email = user_email(creds)
    if not email:
        raise AuthError("Google did not accept that token. Access tokens expire after about an hour, so you may need a fresh one.")
    _domain_ok(email)
    scopes = token_scopes(creds)
    return creds, email, scopes


def token_scopes(creds):
    try:
        r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": creds.token}, timeout=15)
        return sorted((r.json().get("scope") or "").split()) if r.ok else []
    except Exception:  # noqa: BLE001
        return []


def has_data_scopes(scopes):
    return any("analytics" in s for s in scopes) or any("tagmanager" in s for s in scopes)


# ================================================================== both
def user_email(creds):
    try:
        r = AuthorizedSession(creds).get("https://openidconnect.googleapis.com/v1/userinfo", timeout=15)
        return r.json().get("email", "") if r.ok else ""
    except Exception:  # noqa: BLE001
        return ""
