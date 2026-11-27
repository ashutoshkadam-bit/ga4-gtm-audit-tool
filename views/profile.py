"""Profile and credentials: connect a Google account with the shared sign-in, your own OAuth client, or a pasted token."""
import streamlit as st

from gga import __version__, auth, ui

S = st.session_state
WEB = auth.is_web()
DATA_KEYS = ("ga4_rows", "gtm_rows", "results", "known_ids", "auditor", "site_findings", "page_findings", "page_runs", "limited_findings")

ui.page_title("Profile and credentials", "Connect your own Google account. Choose how: the shared sign-in, your own OAuth client, "
              "or a token you paste. Everything is used directly from this browser session.")


def connect(creds, source, mail="", scopes=None):
    """Makes these credentials the active ones and clears data that belonged to the previous account."""
    for k in DATA_KEYS:
        S.pop(k, None)
    S["creds"] = creds
    S["auth_source"] = source
    S["email"] = mail or auth.user_email(creds)
    S["scopes"] = scopes if scopes is not None else auth.token_scopes(creds)


creds = ui.get_creds()
mail = ui.email() if creds else ""

# ------------------------------------------------------------------ current connection
with st.container(border=True):
    if creds:
        c1, c2 = st.columns([1, 6], vertical_alignment="center")
        with c1:
            ui._avatar(mail or "?")  # noqa: SLF001
        with c2:
            st.markdown(f"**{mail or 'Connected'}**")
            ui.badges([("Connected", "default"), (S.get("auth_source", "sign-in"), "secondary"),
                       ("Hosted" if WEB else "On this computer", "outline")], key="prof_badges")
        scopes = S.get("scopes") or auth.token_scopes(creds)
        S["scopes"] = scopes
        if scopes:
            names = [s.rsplit("/", 1)[-1] for s in scopes if s.startswith("https://www.googleapis.com/auth/") or s == "openid"]
            st.caption("Access granted: " + ", ".join(names))
            if not auth.has_data_scopes(scopes):
                ui.notice("This connection cannot read Analytics or Tag Manager",
                          "The account is valid but the token does not include Analytics or Tag Manager read access. Reconnect and tick those permissions.", "warn")
        exp = getattr(creds, "expiry", None)
        if exp and not getattr(creds, "refresh_token", None):
            st.caption("This token has no refresh token, so it stops working around " + exp.strftime("%H:%M UTC") + ". Paste a new one when it does.")
        b1, b2 = st.columns([1, 5])
        if b1.button("Sign out", key="prof_signout"):
            ui.sign_out()
            st.rerun()
    else:
        st.markdown("**Not connected yet.** Pick a method below.")

st.markdown("### Connect an account")
tab_shared, tab_own, tab_token, tab_help = st.tabs(["Google sign-in", "My own OAuth client", "Paste a token", "How to get these"])

# ------------------------------------------------------------------ 1. shared sign-in
with tab_shared:
    st.write("The quickest way. You sign in on Google's own page and approve read-only access to Analytics and Tag Manager.")
    if WEB:
        if auth.web_configured():
            try:
                st.link_button("Sign in with Google", auth.web_login_url(), type="primary")
            except auth.AuthError as e:
                ui.notice("Sign-in is not available", str(e), "info")
        else:
            ui.notice("The shared sign-in is not set up on this server",
                      "Use your own OAuth client or paste a token in the next tabs. They work without any server setup.", "info")
        st.caption("Your login is kept only in this browser session on the server and dropped when you sign out or close the tab.")
    else:
        if auth.client_secret_path():
            if st.button("Sign in with Google", type="primary", key="local_signin"):
                with st.spinner("Finish signing in in the browser window that just opened..."):
                    try:
                        connect(auth.sign_in(), "shared sign-in")
                        st.rerun()
                    except auth.AuthError as e:
                        ui.notice("Sign-in did not complete", str(e), "warn")
            st.caption("Your login is saved on this computer in your user folder. Sign out removes it.")
        else:
            ui.notice("No shared sign-in file here", "This copy has no client_secret.json. Use your own OAuth client or paste a token in the next tabs.", "info")

# ------------------------------------------------------------------ 2. own client
with tab_own:
    st.write("Use an OAuth client from **your own** Google Cloud project. Your own quotas and your own test-user list apply, and "
             "nothing depends on a shared client.")
    redirect = auth.redirect_uri() if WEB else "http://localhost  (any port; create the client as type **Desktop app**)"
    st.markdown(f"**Redirect address to register on your client:** `{redirect}`" if WEB else f"**Client type:** Desktop app. Redirect: {redirect}")
    cid = st.text_input("Client ID", key="own_cid", placeholder="1234567890-abc123.apps.googleusercontent.com")
    csec = st.text_input("Client secret", key="own_csec", type="password", placeholder="GOCSPX-...")
    if WEB:
        if cid.strip() and csec.strip():
            try:
                st.link_button("Continue to Google with my client", auth.web_login_url(dict(id=cid.strip(), secret=csec.strip())), type="primary")
            except auth.AuthError as e:
                ui.notice("Check the client details", str(e), "warn")
        else:
            st.button("Continue to Google with my client", disabled=True)
    else:
        if st.button("Sign in with my client", type="primary", disabled=not (cid.strip() and csec.strip())):
            with st.spinner("Finish signing in in the browser window that just opened..."):
                try:
                    connect(auth.sign_in_with_client(cid, csec), "your own client")
                    st.rerun()
                except auth.AuthError as e:
                    ui.notice("Sign-in did not complete", str(e), "warn")
    st.caption("Your client secret is used only to sign you in during this session. It is not written to disk and not shown again.")

# ------------------------------------------------------------------ 3. paste a token
with tab_token:
    st.write("Already have a token? Paste it and start straight away. Nothing is stored beyond this session.")
    kind = st.radio("Token type", ["Access token (works for about an hour)", "Refresh token (lasts, needs its client ID and secret)"], key="tok_kind")
    if kind.startswith("Access"):
        at = st.text_input("Access token", type="password", key="tok_access", placeholder="ya29....")
        rt = tcid = tsec = ""
    else:
        rt = st.text_input("Refresh token", type="password", key="tok_refresh", placeholder="1//0g...")
        tcid = st.text_input("Client ID of the client that issued it", key="tok_cid")
        tsec = st.text_input("Client secret of that client", type="password", key="tok_csec")
        at = ""
    if st.button("Connect with this token", type="primary", key="tok_go"):
        with st.spinner("Checking the token with Google..."):
            try:
                c, m, scopes = auth.creds_from_token(access_token=at, refresh_token=rt, client_id=tcid, client_secret=tsec)
                connect(c, "a pasted token", m, scopes)
                st.rerun()
            except auth.AuthError as e:
                ui.notice("That token did not work", str(e), "warn")
    st.caption("The token needs the scopes analytics.readonly and tagmanager.readonly. A token is as powerful as a password, so only paste your own.")

# ------------------------------------------------------------------ help
with tab_help:
    st.markdown("""
**Create your own OAuth client (once, about 10 minutes)**

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create or choose a project.
2. **APIs and services > Library**: enable **Google Analytics Admin API**, **Google Analytics Data API** and **Tag Manager API**.
3. **Google Auth Platform > Audience**: choose Internal (Workspace) or External. If External and in Testing, add yourself as a test user.
4. **Google Auth Platform > Clients > Create client**:
   - For the hosted tool choose **Web application** and add the redirect address shown in the *My own OAuth client* tab.
   - For the tool on your own computer choose **Desktop app**.
5. Copy the **Client ID** and **Client secret** into the *My own OAuth client* tab.

**Get a token without a client of your own**

Use Google's [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/): select the scopes
`https://www.googleapis.com/auth/analytics.readonly` and `https://www.googleapis.com/auth/tagmanager.readonly`, authorise, exchange the code, then paste the
**access token** here. It lasts about an hour.

**Good to know**

- The tool is read-only: it cannot change anything in Analytics or Tag Manager.
- You only see what the connected Google account can already open.
- If the host restricts sign-in to one company domain, accounts from other domains are refused.
""")
st.caption(f"GA4 & GTM Audit Tool version {__version__}")
