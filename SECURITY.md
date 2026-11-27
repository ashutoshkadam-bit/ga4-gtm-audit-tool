# Security

## Reporting a problem

If you find a security problem, please **do not open a public issue**. Use GitHub's private reporting instead:
the **Security** tab of this repository, then **Report a vulnerability**. Include what you found, how to reproduce it, and what it could
allow. You will get an answer as soon as the maintainers can read it.

## What the tool does with access

- It asks for **read-only** Google access (Analytics and Tag Manager). It cannot change anything in those products.
- Hosted copies keep a person's Google login only in server memory for that browser session. Nothing is written to disk.
- Client IDs, client secrets and tokens a person types on the Profile page are used for that session only and are never logged.
- The Page audit and Live site check refuse addresses on private, local or reserved networks, including requests the page itself makes.

## Things to keep in mind when you deploy

- Never commit `client_secret.json`, tokens or secrets. Use environment variables or your host's secret store.
- Set `GGA_ALLOWED_DOMAIN` on a hosted copy so only your organisation can sign in and open pages from the server.
- Capture files from the Page audit and the Chrome extension can contain personal identifiers such as analytics client IDs. Treat them as personal data.

## Supported versions

Only the latest release on the `main` branch receives fixes.
