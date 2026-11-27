# Deploying the audit tool as a website

The tool has two modes. Without any web settings it runs on a person's own computer (see README.md).
When you set `GGA_REDIRECT_URI` it switches to **web mode**: people open your site's address and click
**Sign in with Google**. Nothing to install for them.

In web mode each person's Google login is held only in server memory for that browser session. It is never
written to disk, and Sign out or closing the tab drops it. Each person still sees only what their own Google
account can open.

## 1. Create a Web OAuth client (once)

In Google Cloud Console, in the project where you enabled the three APIs (Analytics Admin, Analytics Data,
Tag Manager):

1. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
2. Application type: **Web application**. Name: `audit-tool-web`.
3. **Authorized redirect URIs:** add your site's exact public address, for example
   `https://audit.example.com` (no path, no trailing slash). You get the address in step 2 below, so you can
   come back and add it after the first deploy.
4. Copy the **Client ID** and **Client secret**.

On **Google Auth Platform → Audience**, choose **Internal** if the project belongs to your Workspace
organization. Otherwise add every user as a **Test user**. See SETUP_ADMIN.md.

## 2. Settings the site needs

| Setting | Required | Meaning |
| --- | --- | --- |
| `GGA_CLIENT_ID` | yes | From the Web OAuth client |
| `GGA_CLIENT_SECRET` | yes | From the Web OAuth client. Keep it secret. |
| `GGA_REDIRECT_URI` | yes | Your site's public address, exactly as added in step 1 |
| `GGA_ALLOWED_DOMAIN` | recommended | Only this Google Workspace domain may sign in, for example `example.com` |

Set them as environment variables (or, on Streamlit Community Cloud, as secrets). **Never commit them to git.**
This repository is public.

### Optional: people bring their own client or token

Visitors can also sign in with **their own** OAuth client (their client ID and secret) or a pasted token on the Profile page, so the
shared client above is optional. For their own client to work they register this site's address (`GGA_REDIRECT_URI`) as a redirect URI.
`GGA_STATE_KEY` (any long random string) is an optional extra secret used to protect the sign-in redirect; without it the shared client
secret is used, and without either the key lasts only until the server restarts.

## Keeping history on a hosted copy (recommended)

Without a database, a hosted copy remembers history only for the current visit, because free hosts have no permanent disk. To keep it:

1. Create a PostgreSQL database. Free options include **Neon** and **Supabase**; on Google Cloud use **Cloud SQL**.
2. Copy its connection string, for example `postgresql://user:password@host/dbname?sslmode=require`.
3. Set it as a secret named `GGA_DATABASE_URL` (Streamlit secrets or an environment variable). Never commit it to git.
4. Restart the app. The tables are created automatically. The History page now shows "Saved in: your database".

Each signed-in person sees only their own runs. Optional: `GGA_HISTORY_KEEP` sets how many runs are kept per person (default 60).
If the database cannot be reached, the tool does not fail: it falls back to session-only history and says so on the History page.
Backups, retention and access control are your database provider's job. The tables hold finding text, which can include client names.

## 3. Pick a host

### A. Google Cloud Run (recommended)

From the repository folder, with the Google Cloud CLI signed in and the project selected:

```
gcloud run deploy audit-tool --source . --region asia-south1 --allow-unauthenticated ^
  --session-affinity --timeout 3600 --memory 1Gi ^
  --set-env-vars GGA_ALLOWED_DOMAIN=example.com
```

1. The command prints the service URL (for example `https://audit-tool-abc123-el.a.run.app`).
2. Add that URL as an **Authorized redirect URI** on the Web OAuth client (step 1).
3. Set the three remaining settings. Put the client secret in Secret Manager rather than a plain variable:

```
gcloud run services update audit-tool --region asia-south1 ^
  --update-env-vars GGA_CLIENT_ID=YOUR_CLIENT_ID,GGA_REDIRECT_URI=https://YOUR_SERVICE_URL ^
  --update-secrets GGA_CLIENT_SECRET=audit-client-secret:latest
```

`--allow-unauthenticated` only means anyone can reach the sign-in page. Nobody sees any data without a
Google login, and `GGA_ALLOWED_DOMAIN` limits who can sign in. A long audit (250 items) takes 10 to 25 minutes,
so keep `--timeout 3600`.

### B. Streamlit Community Cloud

1. Go to https://share.streamlit.io, sign in with GitHub and create an app from this repository. Main file: `app.py`.
2. In **Advanced settings → Secrets** paste:

```
GGA_CLIENT_ID = "..."
GGA_CLIENT_SECRET = "..."
GGA_REDIRECT_URI = "https://YOUR-APP.streamlit.app"
GGA_ALLOWED_DOMAIN = "example.com"
```

3. Add `https://YOUR-APP.streamlit.app` as an Authorized redirect URI on the OAuth client.

Community Cloud apps are public by default and may sleep when idle, so set `GGA_ALLOWED_DOMAIN`.

### C. Any Docker host

```
docker build -t audit-tool .
docker run -p 8080:8080 -e GGA_CLIENT_ID=... -e GGA_CLIENT_SECRET=... ^
  -e GGA_REDIRECT_URI=https://your.address -e GGA_ALLOWED_DOMAIN=example.com audit-tool
```

Serve it over **https** (Google requires it for any address except localhost).

## Test web mode on your computer first

Add `http://localhost:8501` as a redirect URI on the Web client, then:

```
set GGA_CLIENT_ID=...
set GGA_CLIENT_SECRET=...
set GGA_REDIRECT_URI=http://localhost:8501
.venv\Scripts\python -m streamlit run app.py
```

## The Page audit page and browser hosting

The **Page audit** page drives a real headless Chromium browser. That works out of the box on your own computer and with the
included `Dockerfile` (Cloud Run or any Docker host), which installs the browser and its system libraries.

On **Streamlit Community Cloud** the repository's `packages.txt` installs the system `chromium` package, and the tool starts it through
Playwright. If a server has no browser at all, the Page audit does not show an error: it runs a **limited check** (page HTML and each
Tag Manager container's published script) and points to the Chrome extension, which needs no browser on the server. The **Browser status**
tab on the Page audit page tells you which situation you are in. If a bad `packages.txt` ever blocks a deploy, delete the file and redeploy.

Because the server opens whatever address a signed-in user types, keep `GGA_ALLOWED_DOMAIN` set. The tool refuses addresses on
private or internal networks, including requests the page itself makes.

## Notes

- Refreshing the page signs the person out (their login is only in memory). One click on **Sign in with
  Google** brings them back, with no new consent screen.
- Everyone shares the Google Cloud project's API quota. Ordinary use is far inside the limits.
- Audit results exist only in the person's browser session. Downloads (Excel, HTML, CSV) are generated on request
  and nothing is stored on the server.
