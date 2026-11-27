"""GA4 + GTM Audit. Start it with run.bat (Windows) or ./run.sh (Mac/Linux), or host it (see DEPLOY.md).

This file is the router: page setup, the Google sign-in callback, the header with the profile menu and the navigation.
The pages themselves are in the views folder.
"""
import streamlit as st

from gga import auth, ui

st.set_page_config(page_title="GA4 & GTM Audit", page_icon=":mag:", layout="wide", initial_sidebar_state="collapsed")
ui.inject_css()
S = st.session_state

# ---- Google sends the visitor back here with ?code=... after sign-in (hosted mode)
if auth.is_web() and not S.get("creds") and ("code" in st.query_params or "error" in st.query_params):
    if "code" in st.query_params:
        try:
            creds, source = auth.web_finish(st.query_params["code"], st.query_params.get("state", ""))
            S["creds"], S["auth_source"] = creds, source
            S["email"] = auth.user_email(creds)
            S["scopes"] = auth.token_scopes(creds)
        except auth.AuthError as e:
            S["auth_notice"] = str(e)
    else:
        S["auth_notice"] = ("Google did not complete the sign-in (it was cancelled, or the account or client is not allowed). "
                            "Please try again, or use another method on the Profile page.")
    st.query_params.clear()
    st.rerun()

pages = [
    st.Page("views/audit.py", title="GA4 & GTM audit", icon=":material/fact_check:", default=True),
    st.Page("views/page_audit.py", title="Page audit", icon=":material/travel_explore:", url_path="page-audit"),
    st.Page("views/history.py", title="History", icon=":material/history:", url_path="history"),
    st.Page("views/frameworks.py", title="Guides", icon=":material/menu_book:", url_path="guides"),
    st.Page("views/profile.py", title="Profile", icon=":material/account_circle:", url_path="profile"),
]
page = st.navigation(pages, position="top")
ui.header()
if S.get("auth_notice"):
    ui.notice("Sign-in did not complete", S.pop("auth_notice"), "warn")
page.run()
