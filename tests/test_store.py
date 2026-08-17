"""저장소 계층. 전부 임시 SQLite에서 돌고 네트워크를 쓰지 않는다."""

from __future__ import annotations

import time

import pandas as pd
import pytest

from tests.conftest import make_close


def test_price_roundtrip(db):
    close = make_close(300)
    assert db.save_prices("AAPL", close) == 300

    loaded = db.load_close("AAPL")
    assert len(loaded) == 300
    pd.testing.assert_series_equal(loaded, close, check_names=False)


def test_save_prices_is_idempotent(db):
    """같은 데이터를 두 번 넣어도 행이 늘지 않아야 한다.

    배치가 겹쳐 돌거나 증분 갱신이 하루 겹쳐 받을 때 실제로 발생한다.
    """
    close = make_close(100)
    db.save_prices("AAPL", close)
    db.save_prices("AAPL", close)
    assert len(db.load_close("AAPL")) == 100


def test_incremental_append_extends_series(db):
    full = make_close(200)
    db.save_prices("AAPL", full[:150])
    assert len(db.load_close("AAPL")) == 150

    # 하루 겹쳐서 들어오는 증분
    db.save_prices("AAPL", full[149:])
    merged = db.load_close("AAPL")
    assert len(merged) == 200
    pd.testing.assert_series_equal(merged, full, check_names=False)


def test_upsert_corrects_revised_price(db):
    """분할·배당 소급 반영으로 과거 종가가 바뀌면 덮어써야 한다."""
    close = make_close(50)
    db.save_prices("AAPL", close)

    revised = close.copy()
    revised.iloc[10] = 999.0
    db.save_prices("AAPL", revised)

    assert db.load_close("AAPL").iloc[10] == pytest.approx(999.0)


def test_load_close_returns_none_when_missing(db):
    assert db.load_close("NOPE") is None


def test_instrument_tracks_range_and_status(db):
    close = make_close(120)
    db.save_prices("AAPL", close)

    record = db.get_instrument("AAPL")
    assert record["status"] == "ok"
    assert record["first_date"] == close.index[0].date()
    assert record["last_date"] == close.index[-1].date()
    assert record["prices_updated_at"] > 0


def test_info_roundtrip_maps_provider_fields(db):
    db.save_info("AAPL", {
        "longName": "Apple Inc.", "currency": "USD", "sector": "Technology",
        "trailingPE": 32.5, "beta": 1.21,
    })
    info = db.info_dict(db.get_instrument("AAPL"))
    assert info["longName"] == "Apple Inc."
    assert info["trailingPE"] == pytest.approx(32.5)
    assert info["beta"] == pytest.approx(1.21)


def test_info_dict_drops_missing_keys(db):
    """값이 없는 필드는 아예 빠져야 한다. None이 섞이면 UI에서 '—' 대신
    빈칸이 뜨거나 계산에 None이 흘러든다."""
    db.save_info("AAPL", {"longName": "Apple Inc."})
    info = db.info_dict(db.get_instrument("AAPL"))
    assert "trailingPE" not in info
    assert info["longName"] == "Apple Inc."


def test_mark_unavailable(db):
    db.mark_unavailable("ZZZZ", "없는 티커입니다")
    record = db.get_instrument("ZZZZ")
    assert record["status"] == "unavailable"
    assert "없는" in record["error"]


def test_touch_request_creates_then_increments(db):
    db.touch_request("AAPL")
    assert db.get_instrument("AAPL")["request_count"] == 1
    db.touch_request("AAPL")
    db.touch_request("AAPL")
    assert db.get_instrument("AAPL")["request_count"] == 3


def test_touch_request_preserves_prices(db):
    """조회 카운트를 올리는 upsert가 기존 컬럼을 날리면 안 된다."""
    db.save_prices("AAPL", make_close(60))
    db.touch_request("AAPL")
    assert db.load_close("AAPL") is not None
    assert db.get_instrument("AAPL")["last_date"] is not None


def test_stale_tickers_prefers_popular(db):
    for ticker, count in [("COLD", 0), ("HOT", 50), ("WARM", 5)]:
        db.save_prices(ticker, make_close(30))
        for _ in range(count):
            db.touch_request(ticker)
    # 방금 저장했으므로 max_age=0이면 전부 대상
    assert db.stale_tickers(0, 3) == ["HOT", "WARM", "COLD"]


def test_stale_tickers_skips_fresh_and_unavailable(db):
    db.save_prices("FRESH", make_close(30))
    db.mark_unavailable("GONE", "없음")
    assert db.stale_tickers(3600, 10) == []


def test_macro_respects_max_age(db):
    db.save_macro("riskfree", 0.0431)
    assert db.load_macro("riskfree") == pytest.approx(0.0431)
    assert db.load_macro("riskfree", max_age=3600) == pytest.approx(0.0431)
    assert db.load_macro("riskfree", max_age=0) is None
    assert db.load_macro("nope") is None


def test_report_cache_roundtrip_and_ttl(db):
    payload = {"ticker": "AAPL", "값": 1.5, "nested": {"list": [1, 2, 3]}}
    db.save_report("key1", payload)

    assert db.load_report("key1", ttl=3600) == payload
    assert db.load_report("key1", ttl=0) is None  # 만료
    assert db.load_report("없는키", ttl=3600) is None


def test_report_cache_survives_overwrite(db):
    db.save_report("k", {"v": 1})
    db.save_report("k", {"v": 2})
    assert db.load_report("k", 3600) == {"v": 2}


def test_purge_reports(db):
    db.save_report("old", {"v": 1})
    assert db.purge_reports(older_than=-1) == 1
    assert db.load_report("old", 3600) is None


def test_stats(db):
    db.save_prices("AAPL", make_close(40))
    db.save_report("k", {"v": 1})
    stats = db.stats()
    assert stats["instruments"] == 1
    assert stats["price_rows"] == 40
    assert stats["cached_reports"] == 1
    assert stats["last_ingest"] == pytest.approx(time.time(), abs=60)


def test_zero_ttl_always_expires_even_within_one_clock_tick(db, monkeypatch):
    """`ttl=0` must mean "do not serve from cache", not "expire eventually".

    time.time() commonly returns the same value for consecutive calls on
    Windows, so a save and a load can land on one tick and produce an age of
    exactly 0.0. A `>` comparison then served the cached value and made both
    TTL assertions intermittently fail.
    """
    frozen = 1_800_000_000.0
    monkeypatch.setattr(time, "time", lambda: frozen)

    db.save_report("same-tick", {"v": 1})
    db.save_macro("same-tick", 1.5)

    assert db.load_report("same-tick", ttl=0) is None
    assert db.load_macro("same-tick", max_age=0) is None
    # A real budget still serves the value.
    assert db.load_report("same-tick", ttl=3600) == {"v": 1}
    assert db.load_macro("same-tick", max_age=3600) == pytest.approx(1.5)
