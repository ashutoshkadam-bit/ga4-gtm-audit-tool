import pathlib
import re

import pytest
import requests

from gga import frameworks, knowledge

ROOT = pathlib.Path(__file__).resolve().parent.parent


def check_names_in_code():
    names = set()
    for f in ("gga/core.py", "gga/site.py", "gga/pageanalysis.py"):
        src = (ROOT / f).read_text(encoding="utf-8-sig")
        names |= set(re.findall(r'\bA\(\s*"([^"]+)"', src)) | set(re.findall(r'safe\(\s*"([^"]+)"', src))
    return names | {"Audit", "GA4 ID not in accessible properties"}


def test_every_check_the_code_can_emit_has_a_fix_guide():
    missing = sorted(n for n in check_names_in_code() if n not in knowledge.GUIDES)
    assert not missing, f"add a guide in gga/knowledge.py for: {missing}"


def test_guides_are_complete_and_links_are_https():
    for name, g in knowledge.GUIDES.items():
        assert g["why"].strip() and g["fix"].strip(), name
        if g.get("source"):
            title, url = g["source"]
            assert title and url.startswith("https://"), name


def test_frameworks_are_complete_and_honest_about_their_kind():
    assert len(frameworks.FRAMEWORKS) >= 8
    for f in frameworks.FRAMEWORKS:
        assert f["kind"] in {"Public source", "General practice"}
        assert f["what"] and f["in_tool"] and f["use_when"]
        if f["kind"] == "Public source":
            assert f["sources"], f["name"] + " claims a public source but lists none"
        for title, url in f["sources"]:
            assert url is None or url.startswith("https://")


def test_for_findings_orders_worst_first_and_skips_passes():
    findings = [dict(check="Paused tags", status="WARN"), dict(check="Paused tags", status="WARN"),
                dict(check="Universal Analytics remnants", status="FAIL"), dict(check="Data streams", status="PASS")]
    out = knowledge.for_findings(findings)
    assert [g["check"] for g in out] == ["Universal Analytics remnants", "Paused tags"] and out[1]["WARN"] == 2


def test_unknown_check_has_no_guide_instead_of_crashing():
    assert knowledge.guide("A check that does not exist") is None


@pytest.mark.network
def test_every_documentation_link_still_opens():
    urls = {g["source"][1] for g in knowledge.GUIDES.values() if g.get("source")}
    urls |= {u for f in frameworks.FRAMEWORKS for _, u in f["sources"] if u}
    bad = []
    for u in sorted(urls):
        try:
            r = requests.get(u, timeout=25, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
            if r.status_code not in (200, 202):  # 202 is a normal answer from EUR-Lex's bot check
                bad.append((r.status_code, u))
        except requests.RequestException as e:
            bad.append((type(e).__name__, u))
    assert not bad, bad
