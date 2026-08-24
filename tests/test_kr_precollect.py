"""시총 상위 종목의 종가를 미리 모은다.

종목 허브는 방문할 때 그 자리에서 수집하는 구조다. 사람에게는 그걸로 충분하지만
크롤러에게는 아니다 — 크롤러가 볼 때 페이지가 비어 있다. 2026-08-24 실측으로
국내 2,873종목 중 저장된 종가가 있는 것이 **19개**였다.

로스터 전체를 미리 모으는 것은 쿼터가 아니라 **뜻**에서 틀린다. 아무도
"삼성스팩10호"를 검색하지 않는다. 사람이 실제로 찾는 것은 시총 위쪽 몇백
종목이고, 그 페이지에만 값이 있으면 사이트맵이 광고할 것이 생긴다.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app import config, ingest, kr_stocks, store
from app.kr_stocks import stock_series_spec
from app.providers.base import RateLimited


@pytest.fixture
def roster(db):
    store.save_kr_listings(
        [
            {"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
             "clpr": 268500.0, "flt_rt": 0.0, "mrkt_tot_amt": 1.6e15},
            {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
             "clpr": 1593000.0, "flt_rt": 0.0, "mrkt_tot_amt": 1.1e15},
            {"srtn_cd": "0044K0", "itms_nm": "삼성스팩10호", "mrkt_ctg": "KOSDAQ",
             "clpr": 1986.0, "flt_rt": 0.0, "mrkt_tot_amt": 2.0e10},
        ],
        "20260821",
    )


def test_the_biggest_names_come_first(roster):
    """시총 순이다 — 스팩이 삼성전자보다 먼저 모이면 안 된다."""
    codes = [code for code, _name in store.list_kr_codes_by_market_cap(2)]
    assert codes == ["005930", "000660"]
    assert "0044K0" not in codes


def test_it_only_collects_what_is_missing(roster, monkeypatch):
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 3)
    monkeypatch.setattr(config, "KR_PRECOLLECT_PER_RUN", 10)
    spec = stock_series_spec("005930", "삼성전자")
    store.save_economic_series(
        spec.series_key, provider_id="fsc", provider_series_id="005930",
        metadata_fields={"title": "삼성전자", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=[(dt.date(2026, 8, 20), 268500.0)],
        publisher="금융위원회", publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )
    asked: list[str] = []
    monkeypatch.setattr(kr_stocks, "_fetch_series", lambda code, name: asked.append(code) or 1)

    assert ingest._precollect_kr_stocks() == 2
    assert "005930" not in asked, "이미 있는 종목을 다시 모으지 않는다"
    assert set(asked) == {"000660", "0044K0"}


def test_one_run_takes_only_a_bite(roster, monkeypatch):
    """한 바퀴에 다 모으면 그날의 로스터·지수·ETF가 같은 한도를 못 쓴다."""
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 3)
    monkeypatch.setattr(config, "KR_PRECOLLECT_PER_RUN", 1)
    asked: list[str] = []
    monkeypatch.setattr(kr_stocks, "_fetch_series", lambda code, name: asked.append(code) or 1)

    assert ingest._precollect_kr_stocks() == 1
    assert asked == ["005930"], "시총 큰 것부터 한 종목"


def test_a_rate_limit_stops_the_run_instead_of_burning_the_quota(roster, monkeypatch):
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 3)
    monkeypatch.setattr(config, "KR_PRECOLLECT_PER_RUN", 10)

    def limited(code, name):
        raise RateLimited("daily cap")

    monkeypatch.setattr(kr_stocks, "_fetch_series", limited)
    assert ingest._precollect_kr_stocks() == 0


def test_one_failure_does_not_stop_the_rest(roster, monkeypatch):
    """한 종목의 실패가 나머지를 막지 않는다 — 이 단계는 색인을 위한 덤이다."""
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 3)
    monkeypatch.setattr(config, "KR_PRECOLLECT_PER_RUN", 10)
    asked: list[str] = []

    def flaky(code, name):
        asked.append(code)
        if code == "005930":
            raise ValueError("이 종목만 깨진다")
        return 1

    monkeypatch.setattr(kr_stocks, "_fetch_series", flaky)
    assert ingest._precollect_kr_stocks() == 2
    assert len(asked) == 3


def test_the_switch_can_be_turned_off(roster, monkeypatch):
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 0)
    monkeypatch.setattr(kr_stocks, "_fetch_series", lambda code, name: 1 / 0)
    assert ingest._precollect_kr_stocks() == 0
