# GA4 & GTM Audit Tool

Audit any of your Google Analytics 4 properties and Google Tag Manager containers in a few clicks.
You sign in with **your own Google account**, so you only audit what you already have access to.
The tool is **read-only**: it never changes anything in Analytics or Tag Manager.

## Start it (first time takes about 2 minutes)

1. Install Python 3.10 or newer from https://www.python.org/downloads/ if you do not have it.
   On the first installer screen, tick **Add python.exe to PATH**.
2. Double-click **run.bat** (Mac/Linux: run `./run.sh`). Your browser opens the tool.
3. Click **Sign in with Google** and pick your work account. Approve the two read-only permissions
   (Analytics and Tag Manager).

You never need a Google Cloud account or any technical setup. Next time, step 2 is all you do.

## Use it

1. **Load my accounts.** The tool lists every GA4 and GTM account you can open.
2. **Choose what to audit.** Tick accounts, or type part of a name in the quick filter
   (for example `acme, globex`). Use "Limit per account" for a fast test run.
3. **Run the audit.** A progress bar shows each property and container. A large run (100 properties,
   250 containers) takes 15 to 25 minutes because Google limits how fast its APIs answer.
4. **Read the results** in the tool, then download:
   - **Excel report**: summary, by account, by check, every finding, GA4 IDs.
   - **HTML report**: one file you can email or print to PDF.
   - **CSV**: every finding, one row per check.

## What it checks

**GA4 (per property):** data retention, data streams, enhanced measurement, key events and whether each
fired recently, custom dimensions and metrics, Google Ads and BigQuery links, Google Signals, attribution
settings, currency against time zone, event volume, `page_view`, and share of Unassigned traffic.

**GTM (per container):** live version exists, paused tags, tags with no trigger, unused triggers and
variables, duplicate tags, leftover Universal Analytics tags, hardcoded GA4 IDs, custom HTML count,
default or test tag names, consent settings.

**Across both:** GTM containers whose GA4 ID does not belong to any GA4 property you can access.

Statuses: **FAIL** is broken or missing, **WARN** is a risk or best-practice gap, **INFO** is recorded
for reference, **PASS** is fine, **ERROR** means a check could not run (usually a permission).
Health score = 100 minus 20 per fail and 5 per warn or error.

## What it cannot see

- GA4 internal traffic filters (Google does not expose them through the API). Verify those by hand.
- Unpublished GTM workspace changes. Only the live published version is checked.
- Properties or containers your Google account cannot open.

## Command line (optional)

```
.venv\Scripts\python cli.py --list
.venv\Scripts\python cli.py --accounts "acme,globex" --out results
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Access blocked: app has not completed verification" | Ask the admin to add your email as a test user, or to switch the app to Internal (SETUP_ADMIN.md). |
| "This copy has no client_secret.json" | Ask whoever shared the tool for the full folder. |
| Asked to sign in again after about a week | Normal while the app is in Testing mode. Click Sign in again. |
| Some checks show ERROR | You can see the item but lack permission on part of it, or Google's rate limit hit. Run it again for that account. |
| Very slow | Untick "GA4 data checks" in Options for a faster run. |

Your login is stored only on your computer (in your user folder, `.ga-gtm-audit`). **Sign out** in the sidebar deletes it.

## Deploying for a team

By default the tool runs on each person's computer. It also has a **web mode** that lets you host it on one server so teammates only open a link and sign in with Google. See **DEPLOY.md** (Cloud Run, Streamlit Community Cloud, Docker).

## Scripts

scripts/audit.py is the original standalone audit script and scripts/make_scope_tables.py builds per-item tables from its output. The app and cli.py do the same job and are the supported way to run audits.

