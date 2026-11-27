"""Schedules: run audits automatically and get an alert when something got worse."""
import streamlit as st

from gga import auth, log, schedule, ui

S = st.session_state
if auth.is_web():
    ui.require_login("scheduled audits")
store, note = ui.get_store()
me = ui.owner()

ui.page_title("Schedules", "Run an audit by itself every day, week or month, keep each result in History and get a message when something got worse.")

if note:
    ui.notice("History is in a fallback mode", note, "warn")
if store.mode == "session":
    ui.notice("Scheduled audits need a database",
              "A schedule has to outlive your browser visit, so it is saved in the history database. This copy of the tool has none yet. "
              "The admin sets GGA_DATABASE_URL (see DEPLOY.md) and reboots the app.", "info")
    st.stop()

tab_list, tab_new, tab_how = st.tabs(["My schedules", "New schedule", "How it runs"])


def when(dt):
    return dt.strftime("%d %b %Y %H:%M UTC") if dt else "not yet"


# ------------------------------------------------------------------ list
with tab_list:
    items = schedule.list_for(store, me)
    if not items:
        st.info("No schedules yet. Create one in the New schedule tab.")
    for sc in items:
        icon = {"ok": ":material/check_circle:", "error": ":material/error:"}.get(sc["last_status"], ":material/schedule:")
        state = "" if sc["active"] else "  (paused)"
        with st.expander(f"{sc['name']}  ·  {sc['frequency']}{state}", icon=icon):
            nxt = schedule.next_run(sc)
            st.markdown(f"**Audits:** {'GA4 and GTM' if sc['only'] == 'all' else sc['only'].upper()} for "
                        f"{sc['accounts'] or 'all accounts you can open'}  \n"
                        f"**Last run:** {when(sc['last_run_at'])}  \n"
                        f"**Next run:** {'paused' if nxt is None and not sc['active'] else when(nxt) if nxt else 'at the next automatic run'}  \n"
                        f"**Alerts to:** {', '.join(x for x in [sc['webhook_host'] and 'webhook (' + sc['webhook_host'] + ')', sc['notify_email']] if x) or 'nobody yet'}")
            if sc["last_message"]:
                (st.error if sc["last_status"] == "error" else st.info)(sc["last_message"])
            a, b, c, d = st.columns(4)
            if a.button("Run now", key=f"run_{sc['id']}", help="Runs this audit right now, in this window. A large one can take several minutes."):
                row = schedule.get_row(store, me, sc["id"])
                with st.spinner("Auditing..."):
                    status, msg = schedule.run_one(store, row)
                (st.success if status == "ok" else st.error)(msg)
            if b.button("Pause" if sc["active"] else "Resume", key=f"pause_{sc['id']}"):
                schedule.set_active(store, me, sc["id"], not sc["active"])
                st.rerun()
            if c.button("Delete", key=f"del_{sc['id']}"):
                schedule.remove(store, me, sc["id"])
                log.event("schedule_deleted", user=log.who(ui.email()))
                st.rerun()
            if sc["last_run_id"]:
                d.page_link("views/history.py", label="Open History", icon=":material/history:")

# ------------------------------------------------------------------ create
with tab_new:
    creds = ui.get_creds()
    if not schedule.key_configured():
        ui.notice("Scheduling is not switched on yet",
                  "The admin sets a secret named GGA_SCHEDULE_KEY (any long random text) on the website and on the GitHub repository, then "
                  "reboots the app. It protects the saved sign-ins. See DEPLOY.md.", "warn")
    elif creds is None:
        st.info("Sign in with Google first, so the schedule can use your read-only access.")
        st.page_link("views/profile.py", label="Go to Profile and sign in", icon=":material/person:")
    else:
        with st.form("new_schedule"):
            name = st.text_input("Name", placeholder="Weekly check of Acme")
            c1, c2, c3 = st.columns(3)
            frequency = c1.selectbox("How often", list(schedule.FREQUENCIES), index=1)
            only = c2.selectbox("What to audit", ["all", "ga4", "gtm"], format_func=lambda x: {"all": "GA4 and GTM", "ga4": "GA4 only", "gtm": "GTM only"}[x])
            days = c3.selectbox("GA4 data window", [7, 14, 30, 60, 90], index=2, format_func=lambda x: f"last {x} days")
            accounts = st.text_input("Only accounts whose name contains (optional)", placeholder="acme, globex",
                                     help="Comma separated. Leave empty to audit every account you can open.")
            data_checks = st.checkbox("Include GA4 data checks (slower, more complete)", value=True)
            st.markdown("**Alerts**")
            hook = st.text_input("Webhook address (Slack, Teams, Google Chat, Discord)", placeholder="https://hooks.slack.com/services/...",
                                 help="An https address that accepts a JSON message. It is stored encrypted and never shown again.")
            mail = ""
            if schedule.smtp_configured():
                mail = st.text_input("Email address for alerts (optional)")
            always = st.checkbox("Send a message after every run, not only when something got worse", value=False)
            ok = st.checkbox("I understand this saves an encrypted, read-only Google sign-in so the audit can run when I am not here. "
                             "I can delete the schedule at any time, and I can revoke access in my Google account.")
            go = st.form_submit_button("Create schedule", type="primary")
        if go:
            if not ok:
                st.warning("Please tick the box to confirm.")
            else:
                try:
                    schedule.create(store, me, ui.email(), creds, name, frequency, accounts, only, days, data_checks, hook, mail, always)
                    st.success("Schedule created. It runs at the next automatic run, or use Run now in My schedules.")
                except schedule.ScheduleError as e:
                    ui.notice("Could not create the schedule", str(e), "warn")

# ------------------------------------------------------------------ how it works
with tab_how:
    st.markdown("""
**What happens.** A small program runs once a day (a GitHub Actions job in the tool's repository). It finds schedules that are due,
runs the audit with the saved read-only sign-in, stores the result in **History** and compares it with the previous run. If anything
new or worse appears, it posts to your webhook (and email, if set up).

**Your sign-in.** Only a Google *refresh token* is saved, encrypted, and it can only read Analytics and Tag Manager. Delete the schedule
or remove the app in your Google account (myaccount.google.com, Security, Third-party access) and it stops working.

**If an alert says Google no longer accepts the sign-in.** While your Google Cloud app is in *Testing* mode, Google expires refresh
tokens after 7 days. Ask the admin to publish the app as Internal (Workspace) to avoid this, or just recreate the schedule.

**For the admin** (one-time):
1. Set `GGA_DATABASE_URL` and `GGA_SCHEDULE_KEY` in the website's secrets, then reboot.
2. In the GitHub repository add the same two as Actions secrets (Settings, Secrets and variables, Actions). Optional: `GGA_SMTP_HOST`,
   `GGA_SMTP_PORT`, `GGA_SMTP_USER`, `GGA_SMTP_PASSWORD`, `GGA_SMTP_FROM` for email alerts.
3. The workflow *Scheduled audits* then runs daily. Open the Actions tab to run it by hand or to see its log.

GitHub pauses scheduled workflows in a public repository after 60 days without any repository activity. Run the workflow once by hand to wake it.
""")
