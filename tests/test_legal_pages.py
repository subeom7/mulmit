"""Legal pages must be reachable, honest and independent of every data gate.

These assertions are deliberately about substance rather than wording. The
privacy policy claims the site sets no cookies and holds no accounts, so the
tests check that those claims stay true of the running application, not just of
the prose.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app import config
from app.main import app

PAGES = {
    "/privacy": ("개인정보처리방침", "Privacy Policy"),
    "/terms": ("이용약관", "Terms of Use"),
    "/disclaimer": ("면책 고지", "Disclaimer"),
}


def test_every_legal_page_is_served_in_both_languages(db):
    client = TestClient(app)

    for path, (korean, english) in PAGES.items():
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.text
        # Both languages ship in the DOM, so the page stays readable even if the
        # toggle script never runs.
        assert korean in body, path
        assert english in body, path


def test_legal_pages_do_not_depend_on_a_data_lane(db):
    """A closed provider gate must not take the privacy policy offline."""
    client = TestClient(app)

    assert client.get("/api/market/macro").status_code == 503
    for path in PAGES:
        assert client.get(path).status_code == 200


def test_pages_cross_link_each_other_and_the_dashboard(db):
    client = TestClient(app)

    for path in PAGES:
        body = client.get(path).text
        for other in PAGES:
            if other != path:
                assert f'href="{other}"' in body, f"{path} should link to {other}"
        assert 'href="/"' in body


def test_dashboards_link_to_the_legal_pages(db):
    client = TestClient(app)

    for path in ("/", "/analytics"):
        body = client.get(path).text
        for legal in PAGES:
            assert f'href="{legal}"' in body, f"{path} should link to {legal}"


def test_no_response_sets_a_cookie_as_the_policy_claims(db):
    client = TestClient(app)

    for path in [*PAGES, "/", "/analytics", "/api/status", "/api/health"]:
        response = client.get(path)
        assert "set-cookie" not in {key.lower() for key in response.headers}, path


def test_legal_pages_load_no_third_party_resources(db):
    """The privacy policy says these pages reach no external host. Keep it true."""
    client = TestClient(app)

    for path in PAGES:
        body = client.get(path).text
        externals = re.findall(r'(?:src|href)="(https?://[^"]+)"', body)
        # Outbound links in the prose are fine; loading a remote asset is not.
        assets = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', body)
        assert assets == [], f"{path} must not fetch {assets}"
        assert all("mulmit.com" in url or url.startswith("https://") for url in externals)


def test_disclaimer_states_the_proxy_boundaries_that_matter(db):
    body = TestClient(app).get("/disclaimer").text

    # The single most misleading possible reading of this site is that the
    # synthetic perpetuals are spot prices.
    for symbol in ("xyz:SP500", "xyz:KR200", "xyz:SMSN", "xyz:CL", "xyz:XYZ100"):
        assert symbol in body, symbol
    assert "투자 자문" in body
    assert "not investment advice" in body.lower()
    # Insider filings are relayed, not rolled into a buy/sell signal.
    assert "Form 3" in body


def test_privacy_page_discloses_the_third_party_widget(db):
    body = TestClient(app).get("/privacy").text

    assert "TradingView" in body
    assert "tradingview.com/policies" in body
    # Access logs and rate-limit IP handling are the only server-side processing.
    assert "localStorage" in body


def test_pages_are_served_without_any_provider_configured(db, monkeypatch):
    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", False)
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", False)
    client = TestClient(app)

    for path in PAGES:
        assert client.get(path).status_code == 200


def test_robots_and_sitemap_serve(db):
    client = TestClient(app)

    robots = client.get("/robots.txt")
    sitemap = client.get("/sitemap.xml")

    assert robots.status_code == 200
    assert "Sitemap: https://mulmit.com/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    # 사이트맵은 이제 인덱스다 — 정적 페이지 목록은 sitemap-pages.xml이 든다.
    assert "sitemap-pages.xml" in sitemap.text
    pages = client.get("/sitemap-pages.xml")
    assert "https://mulmit.com/kr" in pages.text
