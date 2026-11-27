"""Shared interface pieces: theme CSS, header with profile menu, metric cards, badges and friendly messages.

Uses shadcn/ui components (MIT licence) through the streamlit-shadcn-ui package, with plain Streamlit fallbacks so a page never
breaks if a component cannot render.
"""
import hashlib

import streamlit as st

from . import __version__, auth, compare, history, log

S = st.session_state

try:
    import streamlit_shadcn_ui as shadcn
except Exception:  # noqa: BLE001
    shadcn = None

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
.stApp, .stMarkdown, p, label, input, textarea { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.block-container { padding-bottom: 3rem; max-width: 1280px; }
h1 { font-weight: 700; letter-spacing: -0.02em; }
h2, h3 { font-weight: 600; letter-spacing: -0.01em; }
/* cards */
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
div[data-testid="stExpander"] { border-radius: 10px; }
div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
button[kind="primary"], button[kind="secondary"] { border-radius: 8px; font-weight: 500; }
div[data-testid="stTabs"] button[role="tab"] { font-weight: 500; }
/* brand bar */
.gga-brand { display:flex; align-items:center; gap:.6rem; font-weight:700; font-size:1.15rem; letter-spacing:-0.01em; }
.gga-dot { width:.7rem; height:.7rem; border-radius:50%; background:#4f46e5; display:inline-block; }
.gga-sub { color: var(--text-color); opacity:.65; font-size:.9rem; margin:-.25rem 0 1rem; }
.gga-pill { display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.75rem; font-weight:600;
            background: rgba(79,70,229,.12); color:#4f46e5; }
.gga-hero { padding:1.6rem 1.8rem; border-radius:16px; border:1px solid rgba(128,128,128,.25);
            background: linear-gradient(135deg, rgba(79,70,229,.08), rgba(14,165,233,.06)); margin-bottom:1rem; }
.gga-hero h2 { margin:0 0 .3rem; }
footer, #MainMenu { visibility: hidden; }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ credentials
def get_creds():
    """Credentials for the current visitor, or None."""
    if auth.is_web():
        return S.get("creds")
    if S.get("creds"):  # pasted token or own client used in local mode this session
        return S["creds"]
    c = auth.load_credentials()
    return c


def email():
    c = get_creds()
    if not c:
        return ""
    if not S.get("email"):
        S["email"] = auth.user_email(c)
    return S.get("email", "")


def sign_out():
    if not auth.is_web():
        auth.sign_out()
    for k in list(S.keys()):
        del S[k]


def require_login(what="this page"):
    """Stops the page with a friendly card if nobody is signed in."""
    creds = get_creds()
    if creds:
        return creds
    st.markdown(f"""<div class="gga-hero"><h2>Sign in to use {what}</h2>
        <div class="gga-sub" style="margin:0">Connect your Google account once. The tool is read-only and shows only what your account can already open.</div></div>""",
                unsafe_allow_html=True)
    c1, c2 = st.columns([1, 3])
    with c1:
        st.page_link("views/profile.py", label="Go to Profile and sign in", icon=":material/person:")
    st.stop()


# ------------------------------------------------------------------ saved history
@st.cache_resource(show_spinner=False)
def _shared_store(url, web):
    """One database connection per server process. Returns (store or None, note)."""
    store, note = history.open_store(None, web, url)
    return (store if store.mode != "session" else None), note


def get_store():
    """The history store for this visitor and a plain-language note about any fallback."""
    web = auth.is_web()
    url = auth._cfg("GGA_DATABASE_URL")  # noqa: SLF001
    note = ""
    if url or not web:
        try:
            store, note = _shared_store(url, web)
        except Exception as e:  # noqa: BLE001
            log.exception("history_store_failed", e)
            store, note = None, "The history database could not be opened, so history is kept for this session only."
        if store is not None:
            return store, note
    return history.SessionStore(S), note


def owner():
    return history.owner_id(email())


def save_history(kind, title, scope_text, findings, meta=None):
    """Saves one run. Never raises: history must not break an audit. Returns the run id or None."""
    try:
        store, _ = get_store()
        rid = store.save_run(owner(), kind, title, scope_text, findings, meta, version=__version__)
        log.event("history_saved", kind=kind, findings=len(findings), where=store.mode)
        return rid
    except Exception as e:  # noqa: BLE001
        log.exception("history_save_failed", e)
        return None


def previous_run(kind, scope_text, exclude=None):
    """The latest saved run of the same kind and scope, or None."""
    try:
        store, _ = get_store()
        for r in store.list_runs(owner(), kind):
            if r["id"] != exclude and r["scope_text"] == scope_text:
                return r, store.get_findings(owner(), r["id"])
    except Exception as e:  # noqa: BLE001
        log.exception("history_read_failed", e)
    return None


def since_last_notice(kind, scope_text, run_id, findings, key):
    """Shows 'since your last run: ...' under a fresh result, or tells the person that history is now saved."""
    prev = previous_run(kind, scope_text, exclude=run_id)
    if prev:
        run, old = prev
        c = compare.compare(old, findings)
        st.success(f"Since your last run on {run['created_at'][:10]}: {compare.headline(c)}.")
        st.page_link("views/history.py", label="See what changed", icon=":material/difference:")
    elif run_id:
        st.info("Saved to history. Run this again later and this page will show what changed since now.")


# ------------------------------------------------------------------ header and profile menu
def header():
    c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
    with c1:
        st.markdown('<div class="gga-brand"><span class="gga-dot"></span>GA4 &amp; GTM Audit</div>', unsafe_allow_html=True)
    with c2:
        connected = bool(get_creds())
        mail = email() if connected else ""
        label = (mail.split("@")[0][:18] if mail else ("Connected" if connected else "Sign in"))
        with st.popover(label, icon=":material/account_circle:", width="stretch"):
            if connected:
                _avatar(mail or "Account")
                st.markdown(f"**{mail or 'Connected account'}**")
                st.caption(f"Connected through {S.get('auth_source', 'your sign-in')}")
                st.page_link("views/profile.py", label="Profile and credentials", icon=":material/manage_accounts:")
                if st.button("Sign out", key="hdr_signout", width="stretch"):
                    sign_out()
                    st.rerun()
            else:
                st.markdown("**Not signed in**")
                st.caption("Connect your own Google account.")
                st.page_link("views/profile.py", label="Sign in", icon=":material/login:")


def _avatar(mail):
    initials = (mail[:2] or "?").upper()
    if shadcn is not None:
        try:
            shadcn.avatar(None, fallback=initials, key="hdr_avatar_" + hashlib.md5(mail.encode()).hexdigest()[:6], size="lg")
            return
        except Exception:  # noqa: BLE001
            pass
    st.markdown(f'<span class="gga-pill">{initials}</span>', unsafe_allow_html=True)


# ------------------------------------------------------------------ building blocks
def page_title(title, subtitle=""):
    st.markdown(f"## {title}")
    if subtitle:
        st.markdown(f'<div class="gga-sub">{subtitle}</div>', unsafe_allow_html=True)


def metrics(items, key):
    """items: list of (label, value, description). Renders shadcn metric cards, falling back to st.metric."""
    cols = st.columns(len(items))
    for i, (label, value, desc) in enumerate(items):
        with cols[i]:
            done = False
            if shadcn is not None:
                try:
                    shadcn.metric_card(label, value, description=desc or None, key=f"{key}_{i}")
                    done = True
                except Exception:  # noqa: BLE001
                    done = False
            if not done:
                st.metric(label, value, help=desc or None)


def badges(items, key):
    """items: list of (text, variant) where variant is default, secondary, destructive or outline."""
    if not items:
        return
    if shadcn is not None:
        try:
            shadcn.badges(items, key=key)
            return
        except Exception:  # noqa: BLE001
            pass
    st.markdown(" ".join(f'<span class="gga-pill">{t}</span>' for t, _ in items), unsafe_allow_html=True)


def notice(title, text, kind="info"):
    """A friendly message instead of an error box. kind: info, warn, error."""
    box = {"info": st.info, "warn": st.warning, "error": st.error}.get(kind, st.info)
    box(f"**{title}**  \n{text}")
