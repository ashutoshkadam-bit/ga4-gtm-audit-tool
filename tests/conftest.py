"""Shared test helpers: synthetic page captures, a local test website, and a browser-availability check."""
import http.server
import pathlib
import socketserver
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def req(url, type="Script", status=200, start=0.0, phase="load", initiator_url="", initiator_type="", headers=None, post="",
        size=1000, method="GET", mime="", error=""):
    """One network request in the capture format."""
    return dict(id=url + str(start), url=url, method=method, type=type, status=status, mime=mime, initiator_type=initiator_type,
                initiator_url=initiator_url, from_cache=False, protocol="h2", ip="1.2.3.4", encoded_size=size, start_ms=start,
                end_ms=start + 50, error=error, resp_headers=headers or {}, post=post, phase=phase, tls="TLS 1.3")


def make_capture(requests, **kw):
    """A complete capture dict (schema gga-capture-1) for https://shop.example.com/ with sensible defaults."""
    base = dict(
        schema="gga-capture-1", source="test", url="https://shop.example.com/", final_url="https://shop.example.com/",
        started="2026-01-01T00:00:00Z", seconds=5, device="desktop", user_agent="test", nav_error="", status=200, doc_headers={},
        requests=requests, requests_dropped=0, console=[], errors=[], cookies=[], storage={}, globals=[],
        perf={"ttfb": 200, "fcp": 900, "lcp": 1800, "cls": 0.02}, datalayer=[], title="Shop", lang="en", scripts=[], meta=[],
        iframes=[], links={}, html="", consent={"tested": False, "clicked": "", "cookies_after": [], "new_requests": 0})
    base.update(kw)
    return base


DOC = "https://shop.example.com/"
GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-TEST123"
GA4 = "https://www.google-analytics.com/g/collect?v=2&tid=G-TEST123456&en={en}&dl=https%3A%2F%2Fshop.example.com%2F"


def doc_request(**kw):
    return req(DOC, type="Document", mime="text/html", **kw)


# ---------------------------------------------------------------- a tiny local website for browser tests
PAGE = """<!doctype html><html lang="en"><head><title>Test page</title>
<script>
window.dataLayer = window.dataLayer || [];
dataLayer.push({event: 'page_ready'});
document.cookie = '_ga=GA1.1.123.456; path=/';
console.error('boom from the test page');
fetch('/g/collect?v=2&tid=G-TEST123456&en=page_view&dl=http%3A%2F%2Flocalhost%2F', {method: 'POST', body: '', keepalive: true});
var s = document.createElement('script'); s.src = '/dyn.js'; document.head.appendChild(s);
</script></head><body><h1>Hello</h1></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep test output quiet
        pass

    def do_GET(self):
        if self.path.startswith("/g/collect"):
            self.send_response(204)
            self.end_headers()
        elif self.path.startswith("/dyn.js"):
            body = b"window.__dyn = 1;"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_POST = do_GET


@pytest.fixture(scope="session")
def local_site():
    """Serves the test page on 127.0.0.1 and returns its base address."""
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser_ready():
    """Skips the test when no headless browser can start on this machine."""
    from gga import pagecapture
    try:
        pagecapture.ensure_browser()
    except pagecapture.BrowserUnavailable:
        pytest.skip("no headless browser available")
