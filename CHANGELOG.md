# Changelog

## 1.3.0 (summaries and scheduled audits)
- An executive **Summary** now opens the audit results and the Page audit overview, and heads the HTML and Excel reports: overall health, what to
  fix first, what to schedule, what could not be checked, the accounts and items that need most attention.
- New **Schedules** page: run an audit daily, weekly or monthly without anyone present, save each run to History and get a webhook
  (Slack, Teams, Google Chat, Discord) or email alert when something is new or got worse. Saved sign-ins are encrypted and read-only.
- New workflow `scheduled-audits.yml` runs the due schedules every day (`python -m gga.schedule`).

## 1.2.0 (history release)
- New **History** page: every audit is saved, and any two runs can be compared (new problems, got worse, fixed, improved, still open,
  health score per item). Trends chart and "problems that keep coming back". Compare against a findings file you downloaded earlier.
- Results pages now say "Since your last run: ..." right after an audit.
- History is stored in a PostgreSQL database when `GGA_DATABASE_URL` is set, in a file on your own computer when running locally,
  or in the browser session only on a hosted copy without a database. Each person sees only their own runs.
- CI now tests against a real PostgreSQL.

## 1.1.0 (foundations release)
- Added an MIT licence, security policy and contributing guide.
- Added an automated test suite (Python and Chrome extension) and continuous integration on GitHub Actions.
- Pinned every direct dependency to a tested version; Dependabot proposes updates weekly.
- Added structured logging and optional error reporting to Sentry (`SENTRY_DSN`), plus privacy-safe usage events.

## 1.0.0
- GA4 and GTM audit, live site check, browser Page audit and Chrome extension, fix guides and frameworks library,
  profile with own OAuth client and tokens, new interface, hosted deployment.
