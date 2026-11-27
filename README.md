# GA4 & GTM Audit Tool

[![CI](https://github.com/ashutoshkadam-bit/ga4-gtm-audit-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/ashutoshkadam-bit/ga4-gtm-audit-tool/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Audit any of your Google Analytics 4 properties and Google Tag Manager containers in a few clicks.
You sign in with **your own Google account**, so you only audit what you already have access to.
The tool is **read-only**: it never changes anything in Analytics or Tag Manager.

## Interface

A top navigation bar (GA4 & GTM audit, Page audit, Guides, Profile) and a profile menu at the top right. The look uses
[shadcn/ui](https://ui.shadcn.com/) components (MIT licence) through the `streamlit-shadcn-ui` package, with a light and dark theme that
follows your system. The first screen after sign-in is the audit; everything else is one click away.

## Profile: connect your own account

Open **Profile** (or the profile menu) to connect a Google account in the way that suits you. Nothing is stored beyond your browser session
on a hosted copy, and the tool stays read-only.

- **Google sign-in:** the shared sign-in the admin set up.
- **My own OAuth client:** type your own client ID and client secret and sign in with them, so your own quotas and test-user list apply.
  On a hosted copy, register the redirect address shown on that tab on your client.
- **Paste a token:** paste an access token (about an hour) or a refresh token with its client ID and secret, and start straight away.

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

## Page audit and Chrome extension

The **Page audit** page (in the sidebar) loads any web address in a real headless Chromium browser and records everything the page does:

- every network request with timing, size, protocol, server IP, response headers and **how it was started** (hard-coded in the page, or
  loaded by Tag Manager, Adobe Launch and so on)
- console messages and script errors, dataLayer pushes, cookies and storage
- the technologies in use: Tag Manager, GA4, Adobe (Analytics, Launch, Web SDK, Target), Meta, Google Ads, other ad, analytics, session
  replay and A/B tools, consent tools, CDN and hosting, CMS and framework. Detection rules are in `gga/techdb.py`.
- each GA4, Adobe and Meta hit decoded (event names, report suites, IDs), duplicate GA4 hits, tags that load outside the tag manager
- speed (server response, first paint, largest paint, layout shift), page weight, compression, caching, security headers
- an optional **consent test**: it compares what loads before any choice with what loads after clicking the cookie banner's accept button

Everything lands in the Findings with fix guides, and in the reports. For logged-in pages or sites that block automated browsers, use the
**Chrome extension** in the `extension` folder: it records the page in your own browser and exports a file you import on the same page.
See `extension/README.md`.

Setup for the browser engine on your own computer: `pip install -r requirements.txt` then `python -m playwright install chromium`
(`run.bat` and `run.sh` do the first part; the page offers a button for the second).

## Fix guides and frameworks library

Every check has a plain-language guide: why it matters, how to fix it, and a link to the official source.

- After an audit, the **How to fix** tab explains each problem found, worst first. The same guides are in the Excel
  report (a "How to fix" sheet) and the HTML report.
- The **Frameworks and fix guides** page (in the sidebar, no sign-in needed) summarises public audit and analytics
  frameworks in our own words, with links: the audit lifecycle, measurement planning, data quality dimensions,
  tag governance, privacy and consent, attribution, sampling and thresholds, and risk-based prioritisation.

Most books and standards are copyrighted, so the tool links to them instead of copying them. A check with no link has
none because no authoritative page was found. Limits and defaults change, so confirm against the linked page before acting.
The content lives in `gga/knowledge.py` and `gga/frameworks.py` and is easy to extend.

## Live site check (optional)

Section 4 of the tool compares what your **websites really load** with what Google Analytics and Tag Manager say.
Paste website addresses (or click **Fill from my selected GA4 accounts** to use each GA4 web stream's address) and run it.
For each page it reports:

- the Tag Manager containers on the page, whether they are in your accounts, and whether there is more than one
- the GA4 measurement IDs the page and its published containers fire, and whether each belongs to a property you can open
- the same GA4 ID loaded twice (in the page and inside GTM), which can double count
- leftover Universal Analytics IDs, plus Google Ads and Meta pixel IDs for reference

It reads public pages only, with plain HTTP requests. It cannot see tags injected by other scripts or test cookie
consent behaviour. Addresses on private or internal networks are refused. Results are included in the Excel and HTML reports.

## What it cannot see

- GA4 internal traffic filters (Google does not expose them through the API). Verify those by hand.
- Unpublished GTM workspace changes. Only the live published version is checked.
- Properties or containers your Google account cannot open.

## Command line (optional)

```
.venv\Scripts\python cli.py --list
.venv\Scripts\python cli.py --accounts "acme,globex" --out results
```

## Development, tests and logging

- `pytest` runs the test suite (about 100 tests, including real-browser tests against a local test page) and `node --test extension/tests`
  tests the Chrome extension. GitHub Actions runs both, plus `ruff check .`, on every push. See `CONTRIBUTING.md`.
- Dependencies are pinned in `requirements.txt` to tested versions. Dependabot proposes updates every week and CI checks them.
- Every important event (sign-in, accounts loaded, audit and page audit runs, errors) is written to standard output as one JSON line, which
  Cloud Run and Streamlit Cloud collect. People are identified only by a short one-way hash, and secrets are never logged.
  Set `GGA_LOG_LEVEL` to change the detail. To also send errors to Sentry, `pip install -r requirements-optional.txt` and set `SENTRY_DSN`.
- Licence: MIT (see `LICENSE`). Security reports: see `SECURITY.md`. Release notes: `CHANGELOG.md`.

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

