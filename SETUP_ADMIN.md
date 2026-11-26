# Admin setup (one time, about 15 minutes)

Teammates do not touch Google Cloud. You create **one shared OAuth client** and put its file
(`client_secret.json`) in the tool folder before sharing it. Each teammate then signs in with their own
Google account, and Google decides what they can see.

## 1. Create the Google Cloud project

Use your **company Google Workspace account**, not a personal Gmail. This matters for step 3.

1. Open https://console.cloud.google.com and create a project, for example `ga4-gtm-audit-tool`.
2. **APIs & Services → Library.** Enable all three:
   - Google Analytics Admin API
   - Google Analytics Data API
   - Tag Manager API

## 2. Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
2. Application type: **Desktop app**. Name it `audit-tool`.
3. Click **Download JSON**. Save it as `client_secret.json` inside the tool folder (next to `app.py`).

## 3. Choose who can sign in (important)

On **Google Auth Platform → Audience** (older UI: OAuth consent screen):

| Option | Who can sign in | Catch |
| --- | --- | --- |
| **Internal** (recommended) | Anyone in your Workspace organization | Only available when the project belongs to your Workspace organization. No test users, and logins do not expire after 7 days. |
| External, Testing | Only emails you list as **Test users** (up to 100) | You add each teammate by hand, and every login expires after 7 days. |

If your project was created under a personal Gmail account, **Internal is not offered**. Create a new
project under your company organization and repeat steps 1 and 2.

If you must use External/Testing: add every teammate under **Test users**, and tell them to expect a
fresh sign-in about once a week. Do not click "Publish app". It triggers Google's verification review.

## 4. Share the tool

1. Put the whole folder, including `client_secret.json`, on an internal share (a company drive or a
   private repo). Do not post it publicly.
2. Teammates follow `README.md`: install Python, double-click `run.bat`, sign in.

`client_secret.json` for a Desktop app is not a password. Google treats it as non-confidential, and
nobody can read data with it unless they sign in with an account that already has access. Still keep it
internal so that strangers cannot use your project's API quota.

## How access works

- The tool asks for three scopes: Analytics read-only, Tag Manager read-only, and email (to show who is
  signed in). It cannot edit anything.
- A teammate sees exactly the GA4 properties and GTM containers their own Google account can open.
  Nothing else is added or granted.
- Tokens are saved per person at `%USERPROFILE%\.ga-gtm-audit\token.json` (Mac/Linux:
  `~/.ga-gtm-audit/token.json`). Nothing is sent to any server other than Google.

## Quotas

All teammates share your project's Google API quota. Normal use (a few audits a day) is far inside the
limits. If many people run full-estate audits at once you may see rate-limit ERROR rows. Re-run those
accounts a few minutes later.

## Move to a hosted web version later

This version runs on each person's computer because Google's desktop sign-in needs a local browser.
To host it on one internal server so nobody installs anything, create a **Web application** OAuth client
with your server's address as the redirect URI and replace `sign_in()` in `gga/auth.py` with a web
redirect flow. The audit engine (`gga/core.py`) and reports (`gga/report.py`) need no changes.
