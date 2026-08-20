"""한국은행 ECOS 클라이언트 — 픽스처로만 돈다.

고정하는 것: 월 주기 TIME(YYYYMM)이 월초 날짜가 되고, DATA_VALUE 빈 문자열은
결측으로 남으며(0 아님), 오류는 200 응답의 RESULT 봉투로 오고, 게이트가 꺼진
기본 배포에서 ingest는 아무것도 부르지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app import config, ingest
from app.providers.base import DataUnavailable
from app.providers.ecos import ECOS_SERIES_BY_KEY, EcosProvider

BASE_RATE = ECOS_SERIES_BY_KEY["kr_base_rate"]

BODY = json.dumps({
    "StatisticSearch": {
        "list_total_count": 3,
        "row": [
            {"STAT_CODE": "722Y001", "TIME": "202506", "DATA_VALUE": "3", "UNIT_NAME": "연%"},
            {"STAT_CODE": "722Y001", "TIME": "202507", "DATA_VALUE": "2.75", "UNIT_NAME": "연%"},
            # 발표 전의 달은 값이 빈 문자열로 온다 — 0이 아니라 결측이어야 한다.
            {"STAT_CODE": "722Y001", "TIME": "202508", "DATA_VALUE": "", "UNIT_NAME": "연%"},
        ],
    }
}).encode()

ERROR_BODY = json.dumps({
    "RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다."}
}).encode()


class Transport:
    def __init__(self, body=BODY):
        self.body = body
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        return self.body


def make_provider(transport=None, **kwargs):
    kwargs.setdefault("request_interval", 0.0)
    kwargs.setdefault("retry_backoff", 0.0)
    kwargs.setdefault("sleep", lambda _s: None)
    return EcosProvider("test-key", http_get=transport or Transport(), **kwargs)


def test_monthly_rows_become_first_of_month_and_blanks_stay_absent():
    transport = Transport()
    metadata, observations = make_provider(transport).fetch_series(
        BASE_RATE, start=dt.date(2025, 6, 1), end=dt.date(2025, 8, 31)
    )

    assert dict(observations) == {
        dt.date(2025, 6, 1): 3.0,
        dt.date(2025, 7, 1): 2.75,
    }
    assert metadata["units"] == "연%"
    assert metadata["observation_end"] == "2025-07-01"
    # URL은 stat/cycle/from/to/item 순서를 지킨다.
    assert "/722Y001/M/202506/202508/0101000" in transport.urls[0]


def test_result_envelope_is_an_error_not_data():
    with pytest.raises(DataUnavailable, match="INFO-100"):
        make_provider(Transport(ERROR_BODY)).fetch_series(
            BASE_RATE, start=dt.date(2025, 1, 1)
        )


def test_missing_key_refuses_construction():
    with pytest.raises(ValueError):
        EcosProvider("")


def test_lane_closed_by_default_calls_nothing(db, monkeypatch):
    monkeypatch.setattr(
        ingest, "EcosProvider", lambda *_a, **_k: pytest.fail("provider must not be built")
    )
    assert ingest.refresh_ecos()["skipped"] == "disabled"

    monkeypatch.setattr(config, "ECOS_ENABLED", True)
    assert ingest.refresh_ecos()["skipped"] == "not_configured"


def test_daily_cycle_builds_yyyymmdd_urls_and_parses_eight_digit_times():
    """환율 시리즈(D 주기): 요청 날짜와 TIME 모두 YYYYMMDD 형식이다."""
    from app.providers.ecos import ECOS_SERIES_BY_KEY

    spec = ECOS_SERIES_BY_KEY["fx_usdkrw"]
    assert spec.cycle == "D" and spec.stat_code == "731Y001"

    captured = {}

    def http_get(request, timeout):
        captured["url"] = request.full_url
        return json.dumps({"StatisticSearch": {"row": [
            {"TIME": "20260819", "DATA_VALUE": "1411"},
            {"TIME": "20260820", "DATA_VALUE": "1402.5"},
            {"TIME": "20260821", "DATA_VALUE": ""},  # 휴장/미고시 — 결측 유지
        ]}}).encode("utf-8")

    provider = EcosProvider("k", http_get=http_get, retries=0, request_interval=0.0)
    metadata, observations = provider.fetch_series(
        spec, start=dt.date(2026, 8, 14), end=dt.date(2026, 8, 21)
    )

    assert "/731Y001/D/20260814/20260821/0000001" in captured["url"]
    assert observations == (
        (dt.date(2026, 8, 19), 1411.0),
        (dt.date(2026, 8, 20), 1402.5),
    )
    assert metadata["frequency_short"] == "D"
