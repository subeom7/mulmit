"""수집 배치. 특히 레이트리밋 백오프.

막힌 상태에서 매 주기 계속 노크하면 밴이 풀리지 않고 연장된다.
실제로 개발 중에 이걸로 몇 시간을 날렸다.
"""

from __future__ import annotations

import pytest

from app import config, data, ingest, store
from app.providers.base import DataUnavailable, RateLimited
from tests.conftest import FakeProvider, make_close

pytestmark = pytest.mark.usefixtures("legacy_price_data")


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(ingest, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(config, "INGEST_DELAY", 0.0)
    return fake


def test_backoff_grows_then_caps(db):
    waits = [ingest._apply_backoff() for _ in range(8)]

    assert waits[0] < waits[1] < waits[2], "백오프가 늘어나지 않는다"
    assert all(w <= config.INGEST_BACKOFF_MAX for w in waits), "상한을 넘었다"
    assert waits[-1] == config.INGEST_BACKOFF_MAX


def test_backoff_clears_on_success(db):
    ingest._apply_backoff()
    assert ingest._backoff_remaining() > 0

    ingest._clear_backoff()
    assert ingest._backoff_remaining() == 0


def test_run_once_skips_while_backing_off(db, provider):
    ingest._apply_backoff()

    result = ingest.run_once()
    assert result["skipped"] == "backoff"
    assert provider.price_calls == [], "백오프 중인데 공급자를 불렀다"


def test_explicit_tickers_ignore_backoff(db, provider):
    """수동 실행(`python -m app.ingest AAPL`)은 백오프를 무시한다.

    사람이 직접 부른 건 의도가 명확하다.
    """
    ingest._apply_backoff()

    ingest.run_once(["AAPL"])
    assert len(provider.price_calls) == 1


def test_rate_limit_stops_the_round_and_sets_backoff(db, monkeypatch):
    fake = FakeProvider(fail=RateLimited("막힘"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(ingest, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(config, "INGEST_DELAY", 0.0)
    monkeypatch.setattr(config, "SEED_TICKERS", ["AAA", "BBB", "CCC", "DDD"])

    result = ingest.run_once()

    assert result["rate_limited"] == 1
    assert result["attempted"] == 1, "막힌 뒤에도 계속 두드렸다"
    assert ingest._backoff_remaining() > 0


def test_successful_round_clears_backoff(db, provider, monkeypatch):
    monkeypatch.setattr(config, "SEED_TICKERS", ["AAPL"])
    ingest._apply_backoff()

    result = ingest.run_once(["AAPL"])  # 수동 실행이라 백오프를 뚫는다

    assert result["updated"] == 1
    assert ingest._backoff_remaining() == 0, "성공했는데 백오프가 남아 있다"


def test_missing_ticker_does_not_trigger_backoff(db, monkeypatch):
    """없는 티커는 레이트리밋이 아니다. 백오프를 걸면 안 된다."""
    fake = FakeProvider(fail=DataUnavailable("없는 티커"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(ingest, "get_provider", lambda *a, **k: fake)
    monkeypatch.setattr(config, "INGEST_DELAY", 0.0)

    result = ingest.run_once(["ZZZZ"])

    assert result["missing"] == 1
    assert ingest._backoff_remaining() == 0


def test_fresh_tickers_are_skipped(db, provider, monkeypatch):
    """방금 갱신한 티커를 또 받아오면 그게 레이트리밋의 원인이 된다."""
    monkeypatch.setattr(config, "SEED_TICKERS", ["AAPL"])
    monkeypatch.setattr(config, "MARKET_TICKER", "AAPL")

    ingest.run_once()
    calls_after_first = len(provider.price_calls)

    ingest.run_once()
    assert len(provider.price_calls) == calls_after_first, "신선한 티커를 다시 받았다"


def test_run_once_purges_expired_reports(db, provider, monkeypatch):
    monkeypatch.setattr(config, "SEED_TICKERS", [])
    monkeypatch.setattr(config, "REPORT_TTL", -1)  # 전부 만료 상태로
    store.save_report("old", {"v": 1})

    result = ingest.run_once()
    assert result["purged_reports"] == 1


def test_seed_and_market_tickers_are_always_targeted(db, provider, monkeypatch):
    monkeypatch.setattr(config, "MARKET_TICKER", "^GSPC")
    monkeypatch.setattr(config, "SEED_TICKERS", ["AAPL", "MSFT"])

    ingest.run_once()

    fetched = {call[0] for call in provider.price_calls}
    assert {"^GSPC", "AAPL", "MSFT"} <= fetched


def test_sector_etfs_are_always_targeted(db, provider, monkeypatch):
    monkeypatch.setattr(config, "MARKET_TICKER", "^GSPC")
    monkeypatch.setattr(config, "SEED_TICKERS", [])

    ingest.run_once()

    fetched = {call[0] for call in provider.price_calls}
    assert set(config.SECTOR_ETF_TICKERS) <= fetched


def test_batch_size_is_respected(db, provider, monkeypatch):
    monkeypatch.setattr(config, "SEED_TICKERS", [f"T{i}" for i in range(20)])
    monkeypatch.setattr(config, "INGEST_BATCH_SIZE", 5)

    ingest.run_once()
    assert len(provider.price_calls) <= 5


def test_popular_tickers_refresh_first(db, provider, monkeypatch):
    """배치 예산이 모자랄 때 아무도 안 보는 티커부터 받으면 안 된다."""
    monkeypatch.setattr(config, "SEED_TICKERS", [])
    # 이 테스트는 고정 대상이 아닌 동적 대상끼리의 우선순위만 검증한다.
    monkeypatch.setattr(config, "SECTOR_ETF_TICKERS", ())
    monkeypatch.setattr(config, "MARKET_TICKER", "IGNORED")
    monkeypatch.setattr(ingest, "ASSET_TICKERS", ())
    monkeypatch.setattr(ingest, "CORRELATION_TICKERS", ())
    for ticker, hits in [("COLD", 1), ("HOT", 30)]:
        store.save_prices(ticker, make_close(50))
        for _ in range(hits):
            store.touch_request(ticker)

    monkeypatch.setattr(config, "PRICE_MAX_AGE", 0)  # 둘 다 낡음
    monkeypatch.setattr(config, "INGEST_BATCH_SIZE", 2)
    ingest.run_once()

    ordered = [c[0] for c in provider.price_calls if c[0] in {"HOT", "COLD"}]
    assert ordered and ordered[0] == "HOT"


def test_pinned_sector_etfs_rotate_through_small_batches(db, provider, monkeypatch):
    """고정 대상이 배치 한도보다 많아도 뒤쪽 ETF가 영원히 굶지 않는다."""
    monkeypatch.setattr(config, "MARKET_TICKER", config.SECTOR_ETF_TICKERS[0])
    monkeypatch.setattr(config, "SEED_TICKERS", [])
    monkeypatch.setattr(config, "INGEST_BATCH_SIZE", 3)

    for _ in range(4):
        result = ingest.run_once()
        assert result["attempted"] <= 3

    fetched = {call[0] for call in provider.price_calls}
    assert set(config.SECTOR_ETF_TICKERS) <= fetched
