# GA4 & GTM Audit Recorder (Chrome extension)

Records a page **in your own browser** and exports a capture file for the audit tool's **Page audit** page. Use it when:

- the page needs a login or a specific state (a cart, a form step, a logged-in area),
- the site blocks automated browsers (you see HTTP 403 in the tool),
- you want to see exactly what your real browser sends, including your own cookie consent choice.

It only **observes**. It never blocks, changes or sends anything. The capture stays on your computer until you upload it.

## Install (about a minute)

1. Open `chrome://extensions` in Chrome (or Edge).
2. Switch on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin the extension from the puzzle-piece menu so the icon is easy to reach.

## Use it

1. Open the page you want to audit and wait for it to settle.
2. Click the extension icon, then **Record and reload the page**. (Reloading lets it see everything from the first request.
   Use **Record without reloading** for pages that cannot be reloaded, such as the middle of a checkout.)
3. Use the page normally. To test consent behaviour, accept the cookie banner, then click **I accepted the cookie banner (mark)**.
   Requests after that are labelled "after consent".
4. Click **Stop and download capture**. A `capture-<site>-<time>.json` file is saved.
5. In the audit tool open **Page audit → Import from the Chrome extension** and upload the file.

## What it records

Every network request (URL, method, type, status, IP, headers such as cache, server and CDN headers, timings), POST bodies of
analytics calls so GA4 and Adobe events can be read, console messages and script errors, dataLayer pushes, which script inserted
each tag (to tell Tag Manager tags from hard-coded ones), cookies and storage names, JavaScript globals that identify technologies,
performance (first paint, largest paint, layout shift) and the page HTML.

## Permissions, and why

| Permission | Why |
| --- | --- |
| webRequest | Watch network requests of the tab being recorded (observe only) |
| tabs, scripting | Read the page URL and ask the page for what it collected when you stop |
| cookies | List cookies for the page and the hosts it contacted |
| storage | Keep a recording safe if the browser pauses the extension |
| all sites | The page you audit can be any site |

The content script runs on every page at load but only keeps data in memory on that page. Nothing is stored or sent until you start a recording
and download the file.

## Limits

- The extension cannot see response sizes on the wire (Chrome does not expose them). It uses the `content-length` header when present, so
  weight figures can be lower than the headless-browser audit.
- It cannot see the HTTP protocol (h2 or h3) of each request.
- The cookie list can include cookies from earlier visits, because Chrome returns every cookie stored for those hosts.
- The capture can contain personal identifiers such as GA client IDs. Share it carefully.
- Needs Chrome or Edge 111 or newer.

## For developers

`globals.js` is generated from the tool's signature list: run `python scripts/gen_extension_globals.py` after editing `gga/techdb.py`.
The capture format is `gga-capture-1`, the same one the headless browser produces, so both feed the same analysis.
