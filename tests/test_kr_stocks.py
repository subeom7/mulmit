"""Korean per-stock search and statistics on the FSC lane.

What these pin: the maths is arithmetic on official closes with no window
computed in disguise on shorter history; search ranks the company someone
meant above substring noise without leaving the process; a cache miss fetches
exactly once under the lock and a failure cannot hammer the API; and the whole
feature fails closed with the lane.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import config, kr_stocks, store
from app.main import app
from app.providers.base import DataUnavailable
from app.providers.fsc import FscProvider, stock_series_spec

TODAY = dt.date(2026, 8, 14)


@pytest.fixture
def fsc_lane(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-key")
    kr_stocks._recent_failures.clear()


def _seed_roster(db):
    db.save_kr_listings(
        [
            {"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
             "isin_cd": "KR7005930003", "clpr": 268000.0, "flt_rt": 4.89, "mrkt_tot_amt": 1.6e15},
            {"srtn_cd": "005935", "itms_nm": "삼성전자우", "mrkt_ctg": "KOSPI",
             "clpr": 187800.0, "flt_rt": 3.1, "mrkt_tot_amt": 1.5e14},
            {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
             "clpr": 1593000.0, "flt_rt": -0.5, "mrkt_tot_amt": 1.1e15},
            {"srtn_cd": "001360", "itms_nm": "삼성제약", "mrkt_ctg": "KOSPI",
             "clpr": 1295.0, "flt_rt": 0.2, "mrkt_tot_amt": 1.0e11},
            {"srtn_cd": "0044K0", "itms_nm": "삼성스팩10호", "mrkt_ctg": "KOSDAQ",
             "clpr": 1986.0, "flt_rt": 0.0, "mrkt_tot_amt": 2.0e10},
        ],
        "2026-08-13",
    )


def _seed_series(db, code="005930", *, days=400, start_price=200000.0):
    values = []
    price = start_price
    for offset in range(days, 0, -1):
        date = TODAY - dt.timedelta(days=offset)
        if date.weekday() >= 5:
            continue
        price *= 1.001
        values.append((date, round(price, 2)))
    spec = stock_series_spec(code, "삼성전자")
    db.save_economic_series(
        spec.series_key,
        provider_id="fsc",
        provider_series_id=code,
        metadata_fields={"title": "삼성전자", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=values,
        publisher="금융위원회",
        publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )
    return values


# --- statistics --------------------------------------------------------------


def test_mdd_is_the_deepest_peak_to_trough_fall():
    observations = [
        (dt.date(2026, 1, 1), 100.0),
        (dt.date(2026, 1, 2), 120.0),   # peak
        (dt.date(2026, 1, 3), 90.0),    # -25% from 120
        (dt.date(2026, 1, 4), 108.0),
        (dt.date(2026, 1, 5), 130.0),   # new peak
        (dt.date(2026, 1, 6), 117.0),   # -10%
    ]

    stats = kr_stocks._stats(observations)

    assert stats["mdd"]["value"] == -25.0
    assert stats["mdd"]["peak_date"] == "2026-01-02"
    assert stats["mdd"]["trough_date"] == "2026-01-03"
    # The current drawdown is measured from the newest peak, not the old one.
    assert stats["drawdown_current"] == -10.0


def test_windows_longer_than_history_are_null_not_shortened():
    """A "5-year return" computed on 400 days of data would be a lie."""
    observations = [(TODAY - dt.timedelta(days=300 - i), 100.0 + i) for i in range(300)]

    stats = kr_stocks._stats(observations)

    assert stats["returns"]["1m"] is not None
    assert stats["returns"]["3m"] is not None
    assert stats["returns"]["5y"] is None
    assert stats["returns"]["3y"] is None


def test_the_drawdown_series_matches_the_close_series_point_for_point():
    observations = [(dt.date(2026, 1, 1 + i), float(v)) for i, v in enumerate([100, 110, 99])]

    stats = kr_stocks._stats(observations)

    assert [o["drawdown"] for o in stats["observations"]] == [0.0, 0.0, -10.0]
    assert [o["close"] for o in stats["observations"]] == [100.0, 110.0, 99.0]


# --- roster search -----------------------------------------------------------


def test_search_ranks_the_exact_name_above_substring_matches(db, fsc_lane):
    _seed_roster(db)

    names = [r["itms_nm"] for r in store.search_kr_listings("삼성전자")]
    assert names[0] == "삼성전자"
    assert names[1] == "삼성전자우"

    # Prefix beats substring even when the substring company is bigger.
    names = [r["itms_nm"] for r in store.search_kr_listings("삼성")]
    assert names[0] == "삼성전자"
    assert "삼성제약" in names

    # An exact code is an exact answer.
    assert store.search_kr_listings("005930")[0]["itms_nm"] == "삼성전자"


def test_search_is_case_insensitive_and_treats_wildcards_as_text(db, fsc_lane):
    db.save_kr_listings(
        [
            {"srtn_cd": "282330", "itms_nm": "BGF리테일", "mrkt_ctg": "KOSPI",
             "clpr": 121000.0, "flt_rt": -1.5, "mrkt_tot_amt": 2.1e12},
            {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
             "clpr": 1593000.0, "flt_rt": -0.5, "mrkt_tot_amt": 1.1e15},
        ],
        "2026-08-21",
    )

    # Roughly a tenth of the roster carries Latin letters. `LIKE` is
    # case-sensitive on PostgreSQL, so lower-cased queries used to find nothing
    # in production while passing here on SQLite.
    for query in ("bgf", "BGF", "Bgf리테일"):
        assert [r["itms_nm"] for r in store.search_kr_listings(query)] == ["BGF리테일"]
    assert [r["itms_nm"] for r in store.search_kr_listings("sk하이닉스")] == ["SK하이닉스"]

    # In a search box `%` and `_` are characters someone typed, not wildcards.
    assert store.search_kr_listings("%") == []
    assert store.search_kr_listings("_") == []
    assert store.search_kr_listings("B_F리테일") == []


def test_each_code_gets_its_own_fetch_lock():
    """One global lock made every cold read queue behind every other one.

    A cold read is one upstream round trip of several seconds, so ten visitors
    opening ten uncollected stocks left the last waiting for all nine ahead.
    The lock's real job — collapsing a stampede on the *same* code into one
    fetch — needs only per-code granularity.
    """
    first = kr_stocks._series_lock("005930")
    assert kr_stocks._series_lock("005930") is first          # same code, same lock
    assert kr_stocks._series_lock("000660") is not first      # different code, no queue


def test_two_uncollected_codes_do_not_wait_for_each_other(db, fsc_lane, monkeypatch):
    started = threading.Barrier(2, timeout=5)

    def slow_fetch(code, name):
        started.wait()          # both must be inside the fetch at once
        time.sleep(0.25)
        db.save_economic_series(
            f"kr_stock_{code}",
            provider_id="fsc",
            provider_series_id=code,
            metadata_fields={"title": code, "units": "KRW", "units_short": "원",
                             "frequency": "Daily", "frequency_short": "D"},
            observations=[(dt.date(2026, 8, 20), 100.0), (dt.date(2026, 8, 21), 101.0)],
            publisher="금융위원회",
            publisher_url="https://www.fsc.go.kr/",
            series_url="https://www.data.go.kr/data/15094808/openapi.do",
            rights_status="approved",
        )
        return 2

    monkeypatch.setattr(kr_stocks, "_fetch_series", slow_fetch)
    _seed_roster(db)

    errors: list[BaseException] = []

    def run(code):
        try:
            kr_stocks.get_analysis(code)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(code,)) for code in ("005930", "000660")]
    began = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    elapsed = time.perf_counter() - began

    # The barrier is the assertion: it only releases if both fetches are running
    # at the same time. Under one global lock the second never reaches it.
    assert not errors, errors
    assert elapsed < 0.5, f"the two codes serialised: {elapsed:.2f}s"


def test_the_roster_is_a_replace_so_delistings_disappear(db, fsc_lane):
    _seed_roster(db)
    db.save_kr_listings(
        [{"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI", "clpr": 1.0}],
        "2026-08-14",
    )

    assert store.search_kr_listings("삼성전자") == []
    assert store.kr_listings_meta()["count"] == 1


def test_search_api_serves_from_the_local_roster(db, fsc_lane):
    _seed_roster(db)

    response = TestClient(app).get("/api/kr/search", params={"q": "하이닉스"})

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["code"] == "000660"
    assert body["as_of"] == "2026-08-13"
    assert "금융위원회" in body["source"]["notice"]


def test_search_fails_closed_with_the_lane(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)

    response = TestClient(app).get("/api/kr/search", params={"q": "삼성"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_stock_data_disabled"
    assert response.headers["cache-control"] == "no-store"


# --- per-stock analysis ------------------------------------------------------


def test_analysis_reads_the_store_without_calling_the_provider(db, fsc_lane, monkeypatch):
    _seed_roster(db)
    _seed_series(db)
    monkeypatch.setattr(kr_stocks, "_fetch_series", lambda *a: pytest.fail("provider called on a warm cache"))

    response = TestClient(app).get("/api/kr/stock/005930")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "삼성전자"
    assert body["currency"] == "KRW"
    assert body["mdd"]["value"] <= 0
    assert body["source"]["provider"] == "fsc"
    assert len(body["observations"]) > 200


def test_a_cache_miss_fetches_once_and_then_serves_from_the_store(db, fsc_lane, monkeypatch):
    _seed_roster(db)
    calls = []

    def fake_fetch(code, name):
        calls.append(code)
        _seed_series(db, code)
        return 1

    monkeypatch.setattr(kr_stocks, "_fetch_series", fake_fetch)
    client = TestClient(app)

    first = client.get("/api/kr/stock/005930")
    second = client.get("/api/kr/stock/005930")

    assert first.status_code == second.status_code == 200
    assert calls == ["005930"]


def test_a_failed_fetch_is_memoised_instead_of_retried_per_request(db, fsc_lane, monkeypatch):
    _seed_roster(db)
    calls = []

    def failing_fetch(code, name):
        calls.append(code)
        raise DataUnavailable("no rows")

    monkeypatch.setattr(kr_stocks, "_fetch_series", failing_fetch)
    client = TestClient(app)

    assert client.get("/api/kr/stock/001360").status_code == 404
    assert client.get("/api/kr/stock/001360").status_code == 404
    assert calls == ["001360"]  # the second request hit the failure memo


def test_an_invalid_code_is_rejected_before_any_lookup(db, fsc_lane):
    response = TestClient(app).get("/api/kr/stock/DROP TABLE")
    assert response.status_code in (404, 422)

    response = TestClient(app).get("/api/kr/stock/ab")
    assert response.status_code == 422


def test_analysis_fails_closed_with_the_lane(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)

    response = TestClient(app).get("/api/kr/stock/005930")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_stock_data_disabled"


# --- day snapshot ------------------------------------------------------------


def _envelope(rows, total=None):
    return json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"totalCount": total if total is not None else len(rows),
                     "items": {"item": rows} if rows else ""},
        }
    }).encode("utf-8")


def test_day_snapshot_probes_back_to_the_last_published_trading_day():
    """Saturday and Sunday return zero rows; Friday is the roster."""
    friday_row = {"basDt": "20260814", "srtnCd": "005930", "itmsNm": "삼성전자",
                  "mrktCtg": "KOSPI", "isinCd": "KR7005930003", "clpr": "274500",
                  "fltRt": "2.43", "mrktTotAmt": "1638515000000000"}
    responses = [
        _envelope([], total=0),          # probe Sunday
        _envelope([], total=0),          # probe Saturday
        _envelope([friday_row], total=1),  # probe Friday: found
        _envelope([friday_row], total=1),  # page 1
    ]
    urls = []

    def http(request, timeout):
        urls.append(request.full_url)
        return responses.pop(0)

    provider = FscProvider("k", http_get=http, retries=0, request_interval=0.0, sleep=lambda _s: None)
    import datetime as _dt
    from unittest.mock import patch
    with patch("app.providers.fsc._kst_today", return_value=_dt.date(2026, 8, 16)):
        bas_dt, rows = provider.fetch_day_snapshot()

    assert bas_dt == "2026-08-14"
    assert rows[0]["srtn_cd"] == "005930"
    assert rows[0]["mrkt_tot_amt"] == 1638515000000000.0
    assert "basDt=20260816" in urls[0] and "basDt=20260814" in urls[2]


# --- index family ------------------------------------------------------------


def _seed_index_snapshot(db):
    db.save_kr_index_snapshot(
        [
            {"idx_nm": "코스피", "idx_csf": "KOSPI시리즈", "clpr": 6813.34, "vs": 234.32,
             "flt_rt": 3.56, "ls_yr_flt_rt": 41.2, "yr_hgst": 6813.34, "yr_hgst_dt": "20260813",
             "yr_lwst": 2500.1, "yr_lwst_dt": "20250811", "trqu": 5.5e8, "tr_prc": 2.1e13,
             "lstg_mrkt_tot_amt": 3.4e15},
            {"idx_nm": "코스피 200", "idx_csf": "KOSPI시리즈", "clpr": 1071.24, "vs": 41.8,
             "flt_rt": 4.06, "ls_yr_flt_rt": 44.0, "yr_hgst": 1071.24, "yr_hgst_dt": "20260813",
             "yr_lwst": 330.0, "yr_lwst_dt": "20250811", "trqu": 1.0e8, "tr_prc": 1.4e13,
             "lstg_mrkt_tot_amt": 3.0e15},
            {"idx_nm": "코스피 200 정보기술", "idx_csf": "KOSPI시리즈", "clpr": 14258.43,
             "vs": 870.0, "flt_rt": 6.5, "ls_yr_flt_rt": 80.0, "yr_hgst": 14258.43,
             "yr_hgst_dt": "20260813", "yr_lwst": 3200.0, "yr_lwst_dt": "20250811",
             "trqu": 3.0e7, "tr_prc": 8.0e12, "lstg_mrkt_tot_amt": 1.2e15},
            {"idx_nm": "코스피 고배당 50", "idx_csf": "테마지수", "clpr": 4665.88, "vs": 8.0,
             "flt_rt": 0.17, "ls_yr_flt_rt": 12.0, "yr_hgst": 4700.0, "yr_hgst_dt": "20260601",
             "yr_lwst": 3900.0, "yr_lwst_dt": "20250901", "trqu": 1.0e6, "tr_prc": 1.0e11,
             "lstg_mrkt_tot_amt": 2.0e14},
            # 동명이지수: KOSDAQ 시리즈의 "코스피 200"은 없지만, 실제 데이터에는
            # "IT 서비스"가 양쪽 시리즈에 존재한다. 같은 상황을 재현한다.
            {"idx_nm": "코스피 200 정보기술", "idx_csf": "KOSDAQ시리즈", "clpr": 1.0, "vs": 0.0,
             "flt_rt": 0.0, "ls_yr_flt_rt": 0.0, "yr_hgst": 1.0, "yr_hgst_dt": "20260101",
             "yr_lwst": 1.0, "yr_lwst_dt": "20260101", "trqu": 0.0, "tr_prc": 0.0,
             "lstg_mrkt_tot_amt": 0.0},
        ],
        "2026-08-13",
    )


def test_a_same_named_index_in_another_class_never_shadows_the_kospi_one(db, fsc_lane):
    """"IT 서비스" exists in both the KOSPI and KOSDAQ series with one name."""
    _seed_index_snapshot(db)

    body = TestClient(app).get("/api/kr/indices").json()
    sectors = next(g for g in body["groups"] if g["id"] == "kospi200-sectors")
    it_row = next(r for r in sectors["rows"] if r["name"] == "코스피 200 정보기술")

    assert it_row["close"] == 14258.43  # the KOSPI-series value, not the twin's 1.0


def test_index_family_serves_curated_groups_from_the_snapshot(db, fsc_lane):
    _seed_index_snapshot(db)

    response = TestClient(app).get("/api/kr/indices")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-08-13"
    headline = next(g for g in body["groups"] if g["id"] == "headline")
    sectors = next(g for g in body["groups"] if g["id"] == "kospi200-sectors")
    assert [r["name"] for r in headline["rows"]] == ["코스피", "코스피 200"]
    assert sectors["rows"][0]["name"] == "코스피 200 정보기술"
    assert sectors["rows"][0]["ytd_percent"] == 80.0
    # Curation is a whitelist: a theme index in the snapshot never leaks in.
    all_names = [r["name"] for g in body["groups"] for r in g["rows"]]
    assert "코스피 고배당 50" not in all_names


def test_index_family_fails_closed_with_the_lane(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)

    response = TestClient(app).get("/api/kr/indices")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_stock_data_disabled"


def test_every_curated_index_name_is_spelled_as_the_dataset_publishes_it():
    """The whitelist is exact-match; a typo silently drops a row forever."""
    from app.kr_stocks import KR_INDEX_HEADLINE, KR_INDEX_SECTORS

    names = list(KR_INDEX_HEADLINE) + list(KR_INDEX_SECTORS)
    assert len(names) == len(set(names))
    # Verified against the live dataset on 2026-08-17; these two are the ones
    # whose spacing is easy to get wrong.
    assert "코스피200제외 코스피지수" in names
    assert "코스피 200 초대형제외 지수" in names


def test_index_snapshot_replace_semantics(db, fsc_lane):
    _seed_index_snapshot(db)
    db.save_kr_index_snapshot(
        [{"idx_nm": "코스피", "idx_csf": "KOSPI시리즈", "clpr": 7000.0, "vs": 1.0,
          "flt_rt": 0.1, "ls_yr_flt_rt": 1.0, "yr_hgst": 7000.0, "yr_hgst_dt": "20260814",
          "yr_lwst": 2500.0, "yr_lwst_dt": "20250811", "trqu": 1.0, "tr_prc": 1.0,
          "lstg_mrkt_tot_amt": 1.0}],
        "2026-08-14",
    )

    assert store.kr_index_snapshot_meta()["count"] == 1
    body = TestClient(app).get("/api/kr/indices").json()
    assert body["as_of"] == "2026-08-14"
    assert body["groups"][0]["rows"][0]["close"] == 7000.0


def test_an_unfinalised_52_week_low_of_zero_is_null_not_a_record():
    """The dataset publishes in-progress 52w lows as 0 with a future date."""
    row = {"basDt": "20260813", "idxNm": "코스피", "idxCsf": "KOSPI시리즈",
           "clpr": "6813.34", "vs": "234.32", "fltRt": "3.56", "lsYrEdVsFltRt": "61.7",
           "yrWRcrdHgst": "6813.34", "yrWRcrdHgstDt": "20260813",
           "yrWRcrdLwst": "0", "yrWRcrdLwstDt": "20260814",
           "trqu": "1", "trPrc": "1", "lstgMrktTotAmt": "1"}
    responses = [_envelope([row], total=1), _envelope([row], total=1)]

    provider = FscProvider("k", http_get=lambda r, t: responses.pop(0),
                           retries=0, request_interval=0.0, sleep=lambda _s: None)
    from unittest.mock import patch
    with patch("app.providers.fsc._kst_today", return_value=dt.date(2026, 8, 13)):
        _bas, rows = provider.fetch_index_day_snapshot()

    assert rows[0]["yr_lwst"] is None
    assert rows[0]["yr_hgst"] == 6813.34
