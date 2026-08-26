"""정부 보도자료 피드.

고정하는 것: 제목·링크·기관만 저장하고 본문(description)은 읽지 않으며,
게시일 없는 항목은 first_seen으로 정직하게 표기되고, 기관 하나의 실패는
그 기관만 지운다.

게시일 픽스처는 "어제"로 계산한다. 달력 날짜를 박아 두면 통합 피드의
최근성 창(signal_feed MAX_AGE_DAYS=7)을 조용히 시효로 넘겨서, 코드는
안 바뀌었는데 어느 날 아침부터 전 PR의 CI가 빨개진다 — 2026-08-27 실측,
2026-08-19 고정 픽스처가 정확히 8일째 되던 날이었다.
"""

from __future__ import annotations

import datetime as dt
from email.utils import format_datetime

import pytest
from fastapi.testclient import TestClient

from app import config, kr_overnight, kr_press, signal_feed
from app.main import app

FSC_XML = """<rss><channel>
<item><title><![CDATA[가계부채 점검회의 개최]]></title><link><![CDATA[https://fsc.example/1]]></link><description><![CDATA[본문은 읽지 않는다]]></description></item>
</channel></rss>"""

_KST = dt.timezone(dt.timedelta(hours=9))
# 어제 13:00 KST — 항상 최근성 창 안이고, 정시라 UTC 환산 검증이 읽기 쉽다.
MOEF_PUBLISHED = (dt.datetime.now(_KST) - dt.timedelta(days=1)).replace(
    hour=13, minute=0, second=0, microsecond=0
)

MOEF_XML = f"""<rss><channel>
<item><title>최근 경제동향 발표</title><link>https://moef.example/2</link><pubDate>{format_datetime(MOEF_PUBLISHED)}</pubDate></item>
</channel></rss>"""


@pytest.fixture
def press(db, monkeypatch):
    monkeypatch.setattr(config, "KR_PRESS_ENABLED", True)


def _fetch(url):
    if "fsc" in url:
        return FSC_XML
    return MOEF_XML


def test_refresh_keeps_titles_and_marks_missing_dates(press):
    result = kr_press.refresh(fetch_xml=_fetch)
    assert result["kept"] == 2

    payload = kr_press.get_press()
    by_url = {i["url"]: i for i in payload["items"]}
    fsc = by_url["https://fsc.example/1"]
    assert fsc["agency"] == "금융위원회"
    assert fsc["date_basis"] == "first_seen"   # 게시일 없는 피드
    moef = by_url["https://moef.example/2"]
    assert moef["date_basis"] == "published"
    expected = MOEF_PUBLISHED.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert moef["at"] == expected  # KST 13:00 → UTC 04:00
    assert "본문" not in str(payload["items"])   # description은 어디에도 없다


def test_one_agency_failing_leaves_the_other(press):
    from app.providers.base import DataUnavailable

    def flaky(url):
        if "fsc" in url:
            raise DataUnavailable("down")
        return MOEF_XML

    result = kr_press.refresh(fetch_xml=flaky)
    assert result["kept"] == 1


def test_route_and_feed_integration(press, monkeypatch):
    # 지수 급변 소스가 테스트에서 네트워크를 부르지 않게 무음 처리
    monkeypatch.setattr(
        kr_overnight, "build_kr_overnight",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in tests")),
    )
    kr_press.refresh(fetch_xml=_fetch)

    ok = TestClient(app).get("/api/kr/press")
    assert ok.status_code == 200
    assert ok.json()["count"] == 2

    feed = signal_feed.build_feed()
    rows = [i for i in feed["items"] if i["kind"] == "kr_press"]
    assert len(rows) == 2
    assert rows[0]["title"]["ko"].startswith("[")


def test_gate_closed_reads_as_503(db):
    assert TestClient(app).get("/api/kr/press").status_code == 503
