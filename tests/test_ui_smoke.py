"""Starts the real app and walks every page in a real browser, checking that no page shows an exception."""
import os
import re
import socket
import subprocess
import sys
import time

import pytest
import requests

from conftest import ROOT

pytestmark = pytest.mark.browser


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GGA_", "SENTRY"))}
    env["GGA_HOME"] = str(tmp_path_factory.mktemp("gga_home"))  # empty home: nobody is signed in
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port), "--server.headless", "true",
                             "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if requests.get(url + "/_stcore/health", timeout=2).text.strip() == "ok":
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        proc.kill()
        pytest.fail("the app did not start")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_every_page_renders_without_an_exception(browser_ready, app_url):
    from playwright.sync_api import sync_playwright
    from gga import pagecapture
    problems, seen = [], {}
    with sync_playwright() as p:
        b = pagecapture.launch_browser(p)
        page = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.goto(app_url)
        page.wait_for_function("document.body.innerText.includes('Sign in to use')", timeout=60000)
        seen["home"] = page.locator("body").inner_text()
        for label, marker in (("Page audit", "Audit a URL"), ("Guides", "Frameworks library"), ("Profile", "Connect an account")):
            page.get_by_role("link", name=re.compile(label)).first.click()
            page.wait_for_function(f"document.body.innerText.includes({marker!r})", timeout=60000)
            page.wait_for_timeout(800)
            seen[label] = page.locator("body").inner_text()
            if page.locator('[data-testid="stException"]').count():
                problems.append((label, page.locator('[data-testid="stException"]').first.inner_text()[:300]))
        b.close()
    assert not problems, problems
    assert "Sign in to use the GA4 and GTM audit" in seen["home"]
    assert "My own OAuth client" in seen["Profile"] and "Paste a token" in seen["Profile"]
    for text in seen.values():
        assert "Traceback" not in text and "Executable doesn't exist" not in text
