# Contributing

## Set up

```
python -m venv .venv
.venv\Scripts\activate          (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium
```

## Check your work

```
ruff check .
pytest                          # fast tests, plus browser tests when Chromium is available
pytest -m network               # also checks that every documentation link still opens
node --test extension/tests     # Chrome extension logic
```

Tests marked `browser` start a real headless Chromium and a local test page. They skip themselves when no browser can start.
Continuous integration (GitHub Actions) runs all of the above on every push and pull request.

## Where things are

| Folder | What is in it |
| --- | --- |
| `app.py`, `views/` | The Streamlit interface: router, header, and the four pages |
| `gga/core.py` | GA4 and GTM audit checks |
| `gga/pagecapture.py`, `gga/pageanalysis.py`, `gga/techdb.py` | Browser page audit: capture, analysis, technology signatures |
| `gga/site.py` | Live site check without a browser, and the private-network guard |
| `gga/auth.py` | Google sign-in, own client and token handling |
| `gga/knowledge.py`, `gga/frameworks.py` | Fix guides and frameworks library |
| `extension/` | Chrome extension (Manifest V3) |

## Adding a check

1. Emit a finding with a new check name (`A("My check", "WARN", "detail")`) in `core.py`, `site.py` or `pageanalysis.py`.
2. Add a guide for it in `gga/knowledge.py` with why it matters, how to fix, and an official source link when one exists.
   The test suite fails if a check has no guide.
3. Add a test that proves the check fires and the check does not fire on clean input.

## Adding a technology

Add one line to `SIGNATURES` in `gga/techdb.py`, then run `python scripts/gen_extension_globals.py` so the extension probes the same
JavaScript globals. Add a test case to `tests/test_techdb.py`.

## Style

Plain, short messages for users. Never show a raw error to a user: catch it, log it with `gga.log`, and show a friendly message.
