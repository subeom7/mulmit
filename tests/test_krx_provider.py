from __future__ import annotations

import datetime as dt
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.krx import (
    DASHBOARD_INDEX_NAMES,
    DASHBOARD_STOCK_CODES,
    KRX_REQUIRED_ATTRIBUTION,
    KrxAuthorizationError,
    KrxConfigurationError,
    KrxProvider,
    find_index,
    find_issue,
)


def _payload(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def _stock_row(code: str, name: str) -> dict[str, str]:
    return {
        "BAS_DD": "20260814",
        "ISU_CD": code,
        "ISU_NM": name,
        "MKT_NM": "KOSPI",
        "SECT_TP_NM": "-",
        "TDD_CLSPRC": "274,500",
        "CMPPREVDD_PRC": "6,500",
        "FLUC_RT": "2.43",
        "TDD_OPNPRC": "270,000",
        "TDD_HGPRC": "275,000",
        "TDD_LWPRC": "268,000",
        "ACC_TRDVOL": "10,000,000",
        "ACC_TRDVAL": "2,700,000,000,000",
        "MKTCAP": "1,600,000,000,000,000",
        "LIST_SHRS": "5,969,782,550",
    }


def _index_row(name: str) -> dict[str, str]:
    return {
        "BAS_DD": "20260814",
        "IDX_CLSS": "대표지수",
        "IDX_NM": name,
        "CLSPRC_IDX": "7,000.00",
        "CMPPREVDD_IDX": "10.00",
        "FLUC_RT": "0.14",
        "OPNPRC_IDX": "6,990.00",
        "HGPRC_IDX": "7,010.00",
        "LWPRC_IDX": "6,980.00",
        "ACC_TRDVOL": "1,000,000",
        "ACC_TRDVAL": "10,000,000,000",
        "MKTCAP": "3,000,000,000,000,000",
    }


def test_fetch_kospi_stock_snapshot_uses_official_query_and_auth_header():
    calls = []

    def fake_get(request, timeout):
        calls.append((request, timeout))
        return _payload(
            {
                "OutBlock_1": [
                    _stock_row("005930", "삼성전자"),
                    _stock_row("000660", "SK하이닉스"),
                ]
            }
        )

    provider = KrxProvider("secret-key", timeout=7.5, retries=0, http_get=fake_get)
    rows = provider.fetch_kospi_stocks(dt.date(2026, 8, 14))

    assert len(calls) == 1
    request, timeout = calls[0]
    parsed = urlparse(request.full_url)
    assert parsed.path == "/svc/apis/sto/stk_bydd_trd"
    assert parse_qs(parsed.query) == {"basDd": ["20260814"]}
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["auth_key"] == "secret-key"
    assert headers["accept"] == "application/json"
    assert timeout == 7.5
    assert find_issue(rows, DASHBOARD_STOCK_CODES["samsung_electronics"])["ISU_NM"] == "삼성전자"
    assert find_issue(rows, DASHBOARD_STOCK_CODES["sk_hynix"])["ISU_NM"] == "SK하이닉스"


def test_index_endpoints_and_explicit_name_selection():
    paths = []

    def fake_get(request, _timeout):
        path = urlparse(request.full_url).path
        paths.append(path)
        name = "코스피" if path.endswith("kospi_dd_trd") else "코스닥"
        return _payload({"OutBlock_1": [_index_row(name)]})

    provider = KrxProvider("secret-key", retries=0, http_get=fake_get)
    bas_date = dt.date(2026, 8, 14)
    kospi = provider.fetch_kospi_indices(bas_date)
    kosdaq = provider.fetch_kosdaq_indices(bas_date)

    assert paths == [
        "/svc/apis/idx/kospi_dd_trd",
        "/svc/apis/idx/kosdaq_dd_trd",
    ]
    assert find_index(kospi, DASHBOARD_INDEX_NAMES["kospi"])["IDX_NM"] == "코스피"
    assert find_index(kosdaq, DASHBOARD_INDEX_NAMES["kosdaq"])["IDX_NM"] == "코스닥"


def test_empty_business_day_is_a_valid_empty_snapshot():
    provider = KrxProvider(
        "secret-key",
        retries=0,
        http_get=lambda _request, _timeout: _payload({"OutBlock_1": []}),
    )

    rows = provider.fetch_kospi_stocks(dt.date(2026, 8, 16))

    assert rows == ()


def test_rate_limit_retries_then_raises_without_exposing_key():
    attempts = 0
    waits = []

    def limited(request, _timeout):
        nonlocal attempts
        attempts += 1
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    secret = "do-not-leak"
    provider = KrxProvider(
        secret,
        retries=2,
        retry_backoff=0.25,
        http_get=limited,
        sleep=waits.append,
    )
    with pytest.raises(RateLimited) as exc_info:
        provider.fetch_kospi_indices(dt.date(2026, 8, 14))

    assert attempts == 3
    assert waits == [0.25, 0.5]
    assert secret not in str(exc_info.value)


def test_unauthorized_api_is_not_retried_and_key_is_not_exposed():
    attempts = 0

    def rejected(request, _timeout):
        nonlocal attempts
        attempts += 1
        raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

    secret = "private-key"
    provider = KrxProvider(secret, retries=2, http_get=rejected)
    with pytest.raises(KrxAuthorizationError, match="not been approved") as exc_info:
        provider.fetch_kospi_stocks(dt.date(2026, 8, 14))

    assert attempts == 1
    assert secret not in str(exc_info.value)


def test_malformed_or_incomplete_official_schema_is_rejected():
    provider = KrxProvider(
        "secret-key",
        retries=0,
        http_get=lambda _request, _timeout: _payload(
            {"OutBlock_1": [{"BAS_DD": "20260814", "ISU_CD": "005930"}]}
        ),
    )

    with pytest.raises(DataUnavailable, match="Invalid or unavailable KRX"):
        provider.fetch_kospi_stocks(dt.date(2026, 8, 14))


def test_configuration_and_public_attribution_contract():
    with pytest.raises(KrxConfigurationError, match="KRX_API_KEY"):
        KrxProvider("  ")
    with pytest.raises(ValueError, match="six-digit"):
        find_issue([], "5930")
    assert KRX_REQUIRED_ATTRIBUTION == "한국거래소 통계정보"
