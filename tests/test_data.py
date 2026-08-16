"""data 파사드 = 저장소 우선, 공급자는 최후 수단.

이 파일이 지키는 계약: **저장소에 데이터가 있으면 공급자를 부르지 않는다.**
이게 깨지면 배포 환경에서 야후 차단이 그대로 사용자에게 노출된다.
"""

from __future__ import annotations

import threading

import pytest

from app import config, data, service
from app.providers.base import DataUnavailable, RateLimited
from tests.conftest import FakeProvider, make_close

pytestmark = pytest.mark.usefixtures("legacy_price_data")


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    return fake


def test_cold_ticker_fetches_once_then_serves_from_store(db, provider):
    first = data.get_close("AAPL")
    assert len(provider.price_calls) == 1

    for _ in range(5):
        again = data.get_close("AAPL")
    assert len(provider.price_calls) == 1, "저장소에 있는데 공급자를 또 불렀다"
    assert len(again) == len(first)


def test_ticker_is_normalized(db, provider):
    data.get_close("  aapl  ")
    assert provider.price_calls[0][0] == "AAPL"
    assert db.get_instrument("AAPL") is not None


def test_empty_ticker_rejected(db, provider):
    with pytest.raises(DataUnavailable):
        data.get_close("   ")
    assert provider.price_calls == []


def test_stale_data_is_served_without_refetch(db, provider, monkeypatch):
    """오래된 데이터라도 즉시 내보낸다. 갱신은 배치의 일이다.

    여기서 공급자를 부르면 사용자가 야후 응답시간을 그대로 떠안는다.
    """
    data.get_close("AAPL")
    monkeypatch.setattr(config, "PRICE_MAX_AGE", 0)  # 전부 낡은 상태로 간주

    data.get_close("AAPL")
    assert len(provider.price_calls) == 1


def test_rate_limited_refresh_falls_back_to_stored_prices(db, provider):
    """배치 갱신 중 레이트리밋이 나도 저장된 값은 그대로 살아 있어야 한다."""
    data.get_close("AAPL")
    stored = len(db.load_close("AAPL"))

    provider.fail = RateLimited("야후 제한")
    assert data.refresh_ticker("AAPL") == stored

    assert db.get_instrument("AAPL")["status"] == "ok"
    assert len(data.get_close("AAPL")) == stored


def test_rate_limited_on_cold_ticker_propagates(db, monkeypatch):
    """저장된 것도 없고 야후도 막혔으면 429가 나가야 한다(500 아님)."""
    fake = FakeProvider(fail=RateLimited("야후 제한"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    with pytest.raises(RateLimited):
        data.get_close("COLD")


def test_missing_ticker_is_negatively_cached(db, monkeypatch):
    fake = FakeProvider(fail=DataUnavailable("없는 티커"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)

    for _ in range(3):
        with pytest.raises(DataUnavailable):
            data.get_close("ZZZZ")

    assert len(fake.price_calls) == 1, "없는 티커로 공급자를 반복 호출했다"


def test_negative_cache_expires(db, monkeypatch):
    fake = FakeProvider(fail=DataUnavailable("없는 티커"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    with pytest.raises(DataUnavailable):
        data.get_close("ZZZZ")

    monkeypatch.setattr(config, "NEGATIVE_TTL", 0)
    with pytest.raises(DataUnavailable):
        data.get_close("ZZZZ")
    assert len(fake.price_calls) == 2, "네거티브 캐시가 만료되지 않았다"


def test_concurrent_cold_requests_fetch_once(db, provider):
    """새 티커에 요청이 몰려도 공급자 호출은 한 번이어야 한다.

    대시보드를 여러 탭에서 열거나 새로고침을 연타하면 실제로 발생한다.
    """
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker():
        try:
            barrier.wait(timeout=5)
            data.get_close("AAPL")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(provider.price_calls) == 1


def test_request_count_is_tracked(db, provider):
    for _ in range(4):
        data.get_close("AAPL")
    assert db.get_instrument("AAPL")["request_count"] == 4


def test_info_served_from_store_after_first_fetch(db, provider):
    data.get_close("AAPL")
    first = data.get_info("AAPL")
    for _ in range(3):
        data.get_info("AAPL")
    assert len(provider.info_calls) == 1
    assert first["longName"] == "테스트 종목"


def test_info_failure_does_not_break_service(db, monkeypatch):
    class NoInfo(FakeProvider):
        def fetch_info(self, ticker):
            raise RuntimeError("info 서버 다운")

    fake = NoInfo()
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    data.get_close("AAPL")
    assert data.get_info("AAPL") == {}


def test_risk_free_rate_cached_then_fallback(db, provider):
    assert data.get_risk_free_rate() == pytest.approx(0.0425)
    assert provider.rate_calls == 1
    assert data.get_risk_free_rate() == pytest.approx(0.0425)
    assert provider.rate_calls == 1, "저장했는데 다시 조회했다"


def test_risk_free_rate_falls_back_to_config(db, monkeypatch):
    fake = FakeProvider(fail=RateLimited("제한"))
    monkeypatch.setattr(data, "get_provider", lambda *a, **k: fake)
    assert data.get_risk_free_rate() == pytest.approx(config.FALLBACK_RISKFREE)


def test_refresh_ticker_uses_incremental_start(db, provider):
    full = make_close(300)
    provider.close = full[:250]
    data.get_close("AAPL")
    assert provider.price_calls[-1][1] is None  # 최초는 전체

    provider.close = full
    data.refresh_ticker("AAPL")
    start = provider.price_calls[-1][1]
    assert start is not None, "증분 갱신인데 전체를 다시 받았다"
    assert start == full[:250].index[-1].date()
    assert len(db.load_close("AAPL")) == 300


def test_refresh_with_no_new_data_keeps_ticker_healthy(db, provider):
    """휴장일 갱신이 멀쩡한 종목을 죽이면 안 된다.

    증분 요청에 빈 응답이 오는 건 정상이다(주말·공휴일·장 시작 전).
    이걸 '없는 티커'로 처리하면 배치가 일요일에 도는 것만으로
    서비스 전체가 404를 뱉는다.
    """
    data.get_close("AAPL")
    before = db.get_instrument("AAPL")["prices_updated_at"]

    # FakeProvider는 새 데이터가 없으면 DataUnavailable을 던진다
    data.refresh_ticker("AAPL")

    record = db.get_instrument("AAPL")
    assert record["status"] == "ok", "휴장일 갱신이 티커를 unavailable로 만들었다"
    assert record["prices_updated_at"] >= before, "재확인 시각이 갱신되지 않았다"
    assert data.get_close("AAPL") is not None


# --- 리포트 캐시 -------------------------------------------------------------


def test_report_cache_hit_skips_recomputation(db, provider, monkeypatch):
    provider.close = make_close(1200, seed=3)
    monkeypatch.setattr(data, "get_market_close", lambda: provider.close * 0.9)

    first = service.build_report("AAPL", n_sims=300, include_series=False)

    calls = {"n": 0}
    real = service.forecast.forecast_mdd

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(service.forecast, "forecast_mdd", counting)
    second = service.build_report("AAPL", n_sims=300, include_series=False)

    assert calls["n"] == 0, "캐시가 있는데 다시 계산했다"
    assert first == second


def test_report_cache_key_separates_parameters(db, provider, monkeypatch):
    provider.close = make_close(1200, seed=4)
    monkeypatch.setattr(data, "get_market_close", lambda: provider.close * 0.9)

    base = service.build_report("AAPL", n_sims=300, include_series=False)
    other = service.build_report(
        "AAPL", n_sims=300, drift_mode="zero", include_series=False
    )
    assert base["forecast"]["headline"] != other["forecast"]["headline"]


def test_report_cache_invalidated_by_new_price(db, provider, monkeypatch):
    """새 거래일이 들어오면 캐시 키가 바뀌어야 한다."""
    full = make_close(1200, seed=5)
    provider.close = full[:1100]
    monkeypatch.setattr(data, "get_market_close", lambda: full * 0.9)

    first = service.build_report("AAPL", n_sims=300, include_series=False)
    db.save_prices("AAPL", full)  # 새 데이터 도착
    second = service.build_report("AAPL", n_sims=300, include_series=False)

    assert first["basic"]["last_date"] != second["basic"]["last_date"]
