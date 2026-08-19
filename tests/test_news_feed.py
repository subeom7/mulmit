"""GDELT 뉴스 lane.

고정하는 것: seendate가 ISO로 변환되고, 429 안내문(200 본문 포함)이
RateLimited로 올라가며, 종목 태그는 닫힌 사전의 단어 경계 매칭뿐이고
(Applebee가 Apple이 되지 않는다), 국내 태그의 등락률은 금융위 로스터의
전일 확정값에서 온다. 인용+링크 조건은 payload에 항상 동반된다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config, news_feed, signal_feed, store
from app.main import app
from app.providers.base import RateLimited
from app.providers.gdelt import GdeltProvider, _seen_iso

BODY = json.dumps({"articles": [
    {"title": "Samsung Electronics beats estimates", "url": "https://ex.com/a",
     "domain": "ex.com", "seendate": "20260819T221500Z", "language": "English",
     "sourcecountry": "South Korea"},
    {"title": "Applebee's opens new branch", "url": "https://ex.com/b",
     "domain": "ex.com", "seendate": "20260819T220000Z", "language": "English",
     "sourcecountry": "US"},
    {"title": "Nvidia and Microsoft rally", "url": "https://ex.com/c",
     "domain": "ex.com", "seendate": "20260819T210000Z", "language": "English",
     "sourcecountry": "US"},
]}).encode()


class Transport:
    def __init__(self, body=BODY):
        self.body = body
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        return self.body


def make_provider(transport=None):
    return GdeltProvider(http_get=transport or Transport(), request_interval=0.0,
                         retry_backoff=0.0, sleep=lambda _s: None)


class GkgProvider:
    """refresh()가 쓰는 벌크 경로의 픽스처 — 파싱은 provider 테스트가 따로 고정한다."""

    def fetch_latest_gkg_titles(self):
        return [
            {"title": "Samsung Electronics beats estimates", "url": "https://ex.com/a",
             "domain": "ex.com", "seendate": "2026-08-19T22:15:00Z", "language": "English", "country": ""},
            {"title": "Applebee's opens new branch", "url": "https://ex.com/b",
             "domain": "ex.com", "seendate": "2026-08-19T22:00:00Z", "language": "English", "country": ""},
            {"title": "Nvidia and Microsoft rally", "url": "https://ex.com/c",
             "domain": "ex.com", "seendate": "2026-08-19T21:00:00Z", "language": "English", "country": ""},
            {"title": "Local bake sale raises funds", "url": "https://ex.com/d",
             "domain": "ex.com", "seendate": "2026-08-19T20:00:00Z", "language": "English", "country": ""},
        ]


def test_seendate_becomes_iso():
    assert _seen_iso("20260819T221500Z") == "2026-08-19T22:15:00Z"
    assert _seen_iso("garbage") is None


def test_courtesy_throttle_message_reads_as_rate_limited():
    transport = Transport(b"Please limit requests to one every 5 seconds ...")
    with pytest.raises(RateLimited):
        make_provider(transport).fetch_articles("samsung")


@pytest.fixture
def gdelt(db, monkeypatch):
    monkeypatch.setattr(config, "GDELT_ENABLED", True)


def test_refresh_tags_titles_with_word_boundaries_and_kr_moves(gdelt):
    store.save_kr_listings(
        [{"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
          "clpr": 268500.0, "flt_rt": -2.19, "mrkt_tot_amt": 1.6e15}],
        "20260819",
    )
    result = news_feed.refresh(GkgProvider())
    assert result["kept"] == 2  # 무관 기사(Applebee·bake sale)는 키워드·사전 모두 불통과

    payload = news_feed.get_news()
    by_url = {a["url"]: a for a in payload["articles"]}
    samsung = by_url["https://ex.com/a"]
    assert samsung["tags"][0]["symbol"] == "005930"
    assert samsung["tags"][0]["change_percent"] == pytest.approx(-2.19)
    assert samsung["tags"][0]["change_basis"] == "t1_close"
    # 단어 경계: Applebee's는 Apple이 아니라 아예 걸러졌다.
    assert "https://ex.com/b" not in by_url
    multi = by_url["https://ex.com/c"]
    assert {t["symbol"] for t in multi["tags"]} == {"NVDA", "MSFT"}
    assert multi["tags"][0]["hub"].startswith("/stock/")
    assert payload["attribution"]["url"] == "https://www.gdeltproject.org/"


def test_gate_and_route(db, gdelt):
    client = TestClient(app)
    assert client.get("/api/news").status_code == 503  # 첫 배치 전

    news_feed.refresh(GkgProvider())
    ok = client.get("/api/news")
    assert ok.status_code == 200
    assert ok.headers["X-Data-Source"] == "GDELT"
    assert ok.json()["count"] == 2


def test_feed_carries_news_with_attribution(db, gdelt, monkeypatch):
    news_feed.refresh(GkgProvider())
    feed = signal_feed.build_feed()

    news = [i for i in feed["items"] if i["kind"] == "news"]
    assert len(news) == 2
    assert news[0]["domain"] == "ex.com"
    assert feed["attribution"]["text"].startswith("News metadata: The GDELT Project")


def test_gate_closed_reads_as_503(db):
    assert TestClient(app).get("/api/news").status_code == 503


def test_gkg_archive_parses_titles_urls_and_stamps():
    import io as _io
    import zipfile

    TAB = chr(9)
    NL = chr(10)
    row = TAB.join(
        ["20260819221500-1", "20260819221500", "1", "ex.com", "https://ex.com/a"]
        + [""] * 21
        + ["<PAGE_TITLE>Samsung Electronics beats estimates</PAGE_TITLE>"]
    )
    no_title = TAB.join(["id", "20260819220000", "1", "ex.com", "https://ex.com/b"] + [""] * 22)
    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.gkg.csv", row + NL + no_title + NL)
    zip_bytes = buffer.getvalue()

    listing = NL.join([
        "78917 md5 http://data.gdeltproject.org/gdeltv2/x.export.CSV.zip",
        "122971 md5 http://data.gdeltproject.org/gdeltv2/x.mentions.CSV.zip",
        "7103994 md5 http://data.gdeltproject.org/gdeltv2/x.gkg.csv.zip",
    ]).encode()

    class BulkTransport:
        def __call__(self, request, timeout):
            return listing if request.full_url.endswith("lastupdate.txt") else zip_bytes

    provider = GdeltProvider(http_get=BulkTransport(), request_interval=0.0,
                             retry_backoff=0.0, sleep=lambda _s: None)
    articles = provider.fetch_latest_gkg_titles()
    assert articles == [{
        "title": "Samsung Electronics beats estimates", "url": "https://ex.com/a",
        "domain": "ex.com", "seendate": "2026-08-19T22:15:00Z",
        "language": "English", "country": "",
    }]
