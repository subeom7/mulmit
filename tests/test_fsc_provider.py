"""Financial Services Commission open-data lane.

These tests pin the things that decide whether a number on the Korea section is
trustworthy: that the service key survives either form data.go.kr hands out,
that a LIKE-filtered response is re-checked against the exact identifier before
anything is stored, that an ambiguous match fails instead of guessing, and that
the official won close never lands on the synthetic-perpetual card.
"""

from __future__ import annotations

import datetime as dt
import json
from urllib.error import HTTPError

import pytest

from app import config, data_rights
from app.providers.base import DataUnavailable, RateLimited
from app.providers.fsc import (
    FSC_PROVIDER_ID,
    FSC_SERIES_BY_KEY,
    FscAuthorizationError,
    FscConfigurationError,
    FscProvider,
    _normalized_key,
)

RAW_KEY = "ab+cd/ef=="
ENCODED_KEY = "ab%2Bcd%2Fef%3D%3D"


def _envelope(rows: list[dict], total: int | None = None) -> bytes:
    return json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "numOfRows": 1000,
                "pageNo": 1,
                "totalCount": len(rows) if total is None else total,
                "items": {"item": rows} if rows else "",
            },
        }
    }).encode("utf-8")


def _gateway_error(code: str, message: str) -> bytes:
    return json.dumps({
        "OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {
                "errMsg": message,
                "returnAuthMsg": message,
                "returnReasonCode": code,
            }
        }
    }).encode("utf-8")


def _index_row(date: str, name: str, close: str, *, idx_csf: str = "KOSPI시리즈") -> dict:
    return {"basDt": date, "idxNm": name, "idxCsf": idx_csf, "clpr": close}


def _stock_row(date: str, code: str, close: str, name: str = "삼성전자") -> dict:
    return {"basDt": date, "srtnCd": code, "itmsNm": name, "clpr": close, "mrktCtg": "KOSPI"}


class _Recorder:
    """Captures request URLs and replays queued responses."""

    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, request, timeout):  # noqa: ANN001 - urllib Request
        self.urls.append(request.full_url)
        return self.responses.pop(0) if self.responses else _envelope([])


def _provider(http, key: str = RAW_KEY) -> FscProvider:
    return FscProvider(key, http_get=http, retries=0, request_interval=0.0, sleep=lambda _s: None)


# --- the service key ---------------------------------------------------------


def test_both_key_forms_data_go_kr_issues_normalize_to_one():
    """The portal shows an encoded and a decoded key for the same credential."""
    assert _normalized_key(RAW_KEY) == ENCODED_KEY
    assert _normalized_key(ENCODED_KEY) == ENCODED_KEY
    # Double-encoding is the failure this prevents: %2F must not become %252F.
    assert "%25" not in _normalized_key(ENCODED_KEY)


def test_the_key_is_sent_without_being_encoded_a_second_time():
    http = _Recorder(_envelope([_index_row("20260814", "코스피", "6977.94")]))
    _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1), end=dt.date(2026, 8, 14)
    )

    assert f"serviceKey={ENCODED_KEY}" in http.urls[0]


def test_enabling_the_lane_without_a_key_is_an_error_not_a_silent_no_op():
    with pytest.raises(FscConfigurationError):
        FscProvider("   ")


# --- error envelopes ---------------------------------------------------------


def test_a_rejected_key_arrives_as_http_200_and_is_still_an_error():
    """data.go.kr reports auth failures inside a 200 body, not as a status."""
    http = _Recorder(_gateway_error("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))

    with pytest.raises(FscAuthorizationError):
        _provider(http).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


def test_an_exhausted_daily_allowance_is_reported_as_rate_limiting():
    http = _Recorder(_gateway_error("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"))

    with pytest.raises(RateLimited):
        _provider(http).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


def test_a_non_success_result_code_never_becomes_an_observation():
    body = json.dumps({
        "response": {"header": {"resultCode": "03", "resultMsg": "NODATA_ERROR"}, "body": {}}
    }).encode("utf-8")

    with pytest.raises(DataUnavailable):
        _provider(_Recorder(body)).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


def test_an_http_failure_is_surfaced_rather_than_stored_as_a_gap():
    def failing(request, timeout):  # noqa: ANN001
        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    with pytest.raises(DataUnavailable):
        _provider(failing).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


# --- response shapes ---------------------------------------------------------


def test_an_empty_result_set_is_an_empty_string_not_an_object():
    """The portal returns items:"" for no rows, which must not crash the parse."""
    with pytest.raises(DataUnavailable, match="no rows"):
        _provider(_Recorder(_envelope([]))).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


def test_a_single_row_arrives_as_an_object_rather_than_a_list():
    body = json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "totalCount": 1,
                "items": {"item": _index_row("20260814", "코스피", "6977.94")},
            },
        }
    }).encode("utf-8")

    _metadata, observations = _provider(_Recorder(body)).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
    )

    assert observations == ((dt.date(2026, 8, 14), 6977.94),)


def test_pages_are_followed_until_total_count_is_reached():
    page_one = _envelope([_index_row("20260813", "코스피", "6813.34")], total=2)
    page_two = _envelope([_index_row("20260814", "코스피", "6977.94")], total=2)
    http = _Recorder(page_one, page_two)

    _metadata, observations = _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
    )

    assert len(http.urls) == 2
    assert [value for _date, value in observations] == [6813.34, 6977.94]


# --- selection ---------------------------------------------------------------


def test_neighbours_returned_by_the_like_filter_are_discarded():
    """`likeSrtnCd=005930` may return more than 005930; only the exact code counts."""
    http = _Recorder(_envelope([
        _stock_row("20260814", "005930", "274500"),
        _stock_row("20260814", "0059301", "999999", name="다른 종목"),
    ]))

    _metadata, observations = _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["samsung_exact"], start=dt.date(2026, 8, 1)
    )

    assert observations == ((dt.date(2026, 8, 14), 274500.0),)


def test_an_index_named_the_same_under_two_classifications_fails_loudly():
    """Two different closes for one name on one day means the filter is not unique."""
    http = _Recorder(_envelope([
        _index_row("20260814", "코스피", "6977.94", idx_csf="KOSPI시리즈"),
        _index_row("20260814", "코스피", "1234.56", idx_csf="KRX시리즈"),
    ]))

    with pytest.raises(DataUnavailable, match="multiple distinct closes"):
        _provider(http).fetch_series(
            FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
        )


def test_an_identical_duplicate_row_is_not_treated_as_a_conflict():
    http = _Recorder(_envelope([
        _index_row("20260814", "코스피", "6977.94"),
        _index_row("20260814", "코스피", "6977.94", idx_csf="KRX시리즈"),
    ]))

    _metadata, observations = _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
    )

    assert observations == ((dt.date(2026, 8, 14), 6977.94),)


def test_unparseable_dates_and_closes_are_dropped_not_defaulted():
    http = _Recorder(_envelope([
        _index_row("20260814", "코스피", "6977.94"),
        _index_row("2026081", "코스피", "1.0"),
        _index_row("20260815", "코스피", "-"),
    ]))

    _metadata, observations = _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2026, 8, 1)
    )

    assert observations == ((dt.date(2026, 8, 14), 6977.94),)


def test_the_request_window_is_a_date_range_in_yyyymmdd():
    http = _Recorder(_envelope([_index_row("20260814", "코스피", "6977.94")]))

    _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"],
        start=dt.date(2026, 1, 2),
        end=dt.date(2026, 8, 14),
    )

    assert "beginBasDt=20260102" in http.urls[0]
    assert "endBasDt=20260814" in http.urls[0]


def test_metadata_records_that_the_value_is_a_close_not_a_live_quote():
    http = _Recorder(_envelope([_stock_row("20260814", "005930", "274500")]))

    metadata, _observations = _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["samsung_exact"], start=dt.date(2026, 8, 1)
    )

    assert metadata["units_short"] == "원"
    assert "실시간 시세가 아닙니다" in metadata["notes"]
    assert "삼성전자" in metadata["notes"]


# --- rights ------------------------------------------------------------------


def test_the_lane_fails_closed_until_a_deployment_opts_in(monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)
    assert data_rights.macro_lane_enabled(FSC_PROVIDER_ID) is False
    assert data_rights.series_values_servable(FSC_PROVIDER_ID, "approved") is False

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    assert data_rights.series_values_servable(FSC_PROVIDER_ID, "approved") is True
    assert data_rights.series_values_servable(FSC_PROVIDER_ID, "pending_rights") is False


def test_opening_this_lane_does_not_open_the_krx_lane(monkeypatch):
    """Two different grants over two different datasets, not one arriving late."""
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "KRX_ENABLED", False)

    report = data_rights.lane_report()
    assert report[f"macro:{FSC_PROVIDER_ID}"]["status"] == "enabled"
    assert config.KRX_ENABLED is False


def test_the_status_report_names_the_variable_an_operator_must_set(monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)
    assert data_rights.lane_report()[f"macro:{FSC_PROVIDER_ID}"]["gate"] == "FSC_ENABLED"


# --- end to end --------------------------------------------------------------


def _seed_kospi(db) -> None:
    db.save_economic_series(
        "kospi_exact",
        provider_id=FSC_PROVIDER_ID,
        provider_series_id="코스피",
        metadata_fields={"title": "코스피", "units": "Index", "units_short": "pt",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=[(dt.date(2026, 8, 13), 6813.34), (dt.date(2026, 8, 14), 6977.94)],
        publisher="금융위원회",
        publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094807/openapi.do",
        rights_status="approved",
    )


def test_a_stored_close_reaches_the_api_only_while_the_lane_is_open(db, monkeypatch):
    from app.macro_dashboard import MacroDataDisabled, build_macro_snapshot

    _seed_kospi(db)

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    served = {item["key"]: item for item in build_macro_snapshot("3y")["series"]}
    assert served["kospi_exact"]["latest"]["value"] == 6977.94
    assert served["kospi_exact"]["source"]["provider"] == FSC_PROVIDER_ID
    assert served["kospi_exact"]["source"]["provider_name"] == "금융위원회"

    # Closing the lane withholds rows that are already in the database, which is
    # the whole point of a serving-side gate rather than an ingestion switch.
    monkeypatch.setattr(config, "FSC_ENABLED", False)
    with pytest.raises(MacroDataDisabled):
        build_macro_snapshot("3y")


def test_the_required_attribution_travels_with_the_values(db, monkeypatch):
    from app.macro_dashboard import attribution_metadata

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    providers = {entry["provider"]: entry for entry in attribution_metadata()["providers"]}

    assert "data.go.kr" in providers[FSC_PROVIDER_ID]["notice"]
    assert providers[FSC_PROVIDER_ID]["terms_url"].startswith("https://www.data.go.kr/")


def test_the_official_close_is_a_different_card_from_the_synthetic_perpetual():
    """The register forbids merging a won close with a USD perpetual."""
    from app.providers.fred import FRED_SERIES_BY_KEY

    assert "samsung_exact" in FRED_SERIES_BY_KEY
    assert FRED_SERIES_BY_KEY["samsung_exact"].key != "samsung"

    monitor = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "app" / "static" / "monitor.js"
    ).read_text(encoding="utf-8")
    # The Korean issue code identifies the official close, so the proxy card
    # must not claim it as an alias or one record would fill both cards.
    samsung_line = next(line for line in monitor.splitlines() if line.strip().startswith("samsung:"))
    assert '"005930"' not in samsung_line
