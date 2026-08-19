"""Server-side FRED provider and dashboard series catalog.

The API key never leaves the ingestion process. Request handlers read only the
normalized database tables populated by :mod:`app.ingest`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import DataError, DataUnavailable, RateLimited

FRED_API_BASE = "https://api.stlouisfed.org/fred"
FRED_SITE_BASE = "https://fred.stlouisfed.org"
FRED_TERMS_URL = "https://fred.stlouisfed.org/legal/terms/"
FRED_API_TERMS_URL = "https://fred.stlouisfed.org/docs/api/terms_of_use.html"
FRED_REQUIRED_NOTICE = (
    "This product uses the FRED® API but is not endorsed or certified by the "
    "Federal Reserve Bank of St. Louis."
)
FRED_USER_TERMS = (
    "By using this application, you agree to be bound by the FRED® API Terms of Use."
)
FRED_RIGHTS_NOTICE = (
    "Individual series may be owned by third parties and subject to additional rights. "
    "Review each series' notes before reuse."
)


@dataclass(frozen=True)
class FredGroup:
    group_id: str
    label_ko: str
    label_en: str


@dataclass(frozen=True)
class FredSeriesSpec:
    series_id: str
    key: str
    group: str
    label_ko: str
    label_en: str
    description_ko: str
    description_en: str
    publisher: str
    publisher_url: str
    # Fail closed: every publicly redistributed series must opt in explicitly.
    public_web: bool = False
    # Publisher-prescribed citation, with ``{date}`` for the retrieval date.
    # Present only where the owner asked for a specific form in writing.
    citation: str | None = None

    @property
    def series_url(self) -> str:
        return f"{FRED_SITE_BASE}/series/{self.series_id}"


FRED_GROUPS = (
    FredGroup("market", "시장", "Market"),
    FredGroup("macro", "매크로", "Macro"),
    FredGroup("liquidity", "유동성", "Liquidity"),
    FredGroup("rates", "정책금리", "Policy Rates"),
    FredGroup("commodities", "원자재", "Commodities"),
    FredGroup("fx", "환율", "Foreign Exchange"),
    FredGroup("korea", "한국 공식 종가", "Korean Official Closes"),
)

_ST_LOUIS_FED = "Federal Reserve Bank of St. Louis"
_ST_LOUIS_FED_URL = "https://www.stlouisfed.org/"
_FED_BOARD = "Board of Governors of the Federal Reserve System"
_FED_BOARD_URL = "https://www.federalreserve.gov/"
_FSC = "금융위원회 (Financial Services Commission)"
_FSC_URL = "https://www.fsc.go.kr/"
_NY_FED = "Federal Reserve Bank of New York"
_NY_FED_URL = "https://www.newyorkfed.org/"

FRED_SERIES = (
    FredSeriesSpec(
        "VIXCLS", "vix", "market", "VIX 변동성", "VIX Volatility",
        "미국 주식시장의 단기 기대 변동성", "Near-term expected U.S. equity volatility",
        "Chicago Board Options Exchange", "https://www.cboe.com/",
        public_web=False,
    ),
    FredSeriesSpec(
        "T10Y2Y", "yield_curve", "market", "장단기 금리차", "10Y–2Y Spread",
        "미국 10년물과 2년물 국채 금리 차", "U.S. 10-year minus 2-year Treasury spread",
        _ST_LOUIS_FED, _ST_LOUIS_FED_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "BAMLH0A0HYM2", "high_yield_spread", "market", "하이일드 스프레드",
        "High-Yield Spread", "미국 하이일드 회사채의 신용 위험 프리미엄",
        "Credit-risk premium on U.S. high-yield corporate bonds",
        "ICE Data Indices, LLC", "https://www.ice.com/market-data/indices",
        public_web=False,
    ),
    # St. Louis Fed granted public display in writing (2026-08-18): FRED API
    # access, the suggested citation with retrieval date (revisions make the
    # access date part of the reference), no charging for access to the series,
    # no Bank marks or implied endorsement.
    FredSeriesSpec(
        "STLFSI4", "financial_stress", "market", "금융스트레스지수",
        "Financial Stress Index", "미국 금융시장 전반의 스트레스 수준",
        "Broad stress conditions in U.S. financial markets", _ST_LOUIS_FED,
        _ST_LOUIS_FED_URL,
        public_web=True,
        citation=(
            "Federal Reserve Bank of St. Louis, St. Louis Fed Financial Stress "
            "Index [STLFSI4], retrieved from FRED, Federal Reserve Bank of "
            "St. Louis; https://fred.stlouisfed.org/series/STLFSI4, {date}."
        ),
    ),
    FredSeriesSpec(
        "DGS10", "treasury_10y", "macro", "미국 10년물 금리", "10-Year Treasury Yield",
        "미국 장기금리의 대표 기준", "Benchmark U.S. long-term interest rate",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "DGS2", "treasury_2y", "macro", "미국 2년물 금리", "2-Year Treasury Yield",
        "통화정책 기대를 가장 민감하게 반영하는 단기 국채 금리",
        "The short-maturity yield most sensitive to policy-rate expectations",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RXI_N.B.KO", "fx_usdkrw", "fx", "원·달러", "USD/KRW",
        "미국 달러 한 단위당 원화 환율의 공식 고시값",
        "The official rate of Korean won per US dollar",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RXI_N.B.JA", "fx_usdjpy", "fx", "엔·달러", "USD/JPY",
        "미국 달러 한 단위당 엔화 환율의 공식 고시값",
        "The official rate of Japanese yen per US dollar",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RXI_N.B.CH", "fx_usdcny", "fx", "위안·달러", "USD/CNY",
        "미국 달러 한 단위당 위안화 환율의 공식 고시값",
        "The official rate of Chinese yuan per US dollar",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RXI$US_N.B.EU", "fx_eurusd", "fx", "유로·달러", "EUR/USD",
        "유로 한 단위당 달러 가격. 앞의 세 계열과 방향이 반대입니다.",
        "US dollars per euro; quoted in the opposite direction to the three above.",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RXI$US_N.B.UK", "fx_gbpusd", "fx", "파운드·달러", "GBP/USD",
        "파운드 한 단위당 달러 가격. 앞의 세 계열과 방향이 반대입니다.",
        "US dollars per British pound; quoted in the opposite direction to the three above.",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "M2SL", "m2", "macro", "미국 M2", "U.S. M2 Money Stock",
        "현금과 예금 등을 포함한 미국 광의통화", "Broad U.S. money stock including cash and deposits",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "UNRATE", "unemployment", "macro", "실업률", "Unemployment Rate",
        "미국 민간 노동력의 실업 비율", "Share of the U.S. civilian labor force unemployed",
        "U.S. Bureau of Labor Statistics", "https://www.bls.gov/",
        public_web=True,
    ),
    FredSeriesSpec(
        "ICSA", "initial_claims", "macro", "신규 실업수당 청구", "Initial Jobless Claims",
        "미국 주간 신규 실업보험 청구 건수", "Weekly U.S. initial unemployment insurance claims",
        "U.S. Employment and Training Administration", "https://www.dol.gov/agencies/eta/",
        public_web=True,
    ),
    FredSeriesSpec(
        "WALCL", "fed_assets", "liquidity", "연준 총자산", "Federal Reserve Total Assets",
        "연방준비제도 연결 대차대조표 총자산", "Total assets on the Federal Reserve balance sheet",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "WRESBAL", "reserve_balances", "liquidity", "연준 지급준비금",
        "Reserve Balances", "연준에 예치된 예금기관 준비금 잔액",
        "Reserve balances held by depository institutions", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "RRPONTSYD", "reverse_repo", "liquidity", "역레포 잔액",
        "Overnight Reverse Repo", "연준의 익일물 역환매조건부채권 잔액",
        "Federal Reserve overnight reverse-repurchase agreements", _NY_FED, _NY_FED_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "WTREGEN", "treasury_general_account", "liquidity", "TGA 잔액",
        "Treasury General Account", "연준에 보관된 미국 재무부 일반계정 잔액",
        "U.S. Treasury General Account balance at the Federal Reserve", _FED_BOARD,
        _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "WRMFNS", "retail_money_market_funds", "liquidity", "리테일 머니마켓펀드",
        "Retail Money Market Funds", "미국 리테일 머니마켓펀드의 주간 잔액",
        "Weekly balance of U.S. retail money market funds", _FED_BOARD,
        _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "SOFR", "sofr", "rates", "SOFR", "SOFR", "미국 담보부 익일물 기준금리",
        "Secured Overnight Financing Rate", _NY_FED, _NY_FED_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "EFFR", "effective_fed_funds", "rates", "유효 연방기금금리",
        "Effective Federal Funds Rate", "미국 은행 간 익일물 실효 정책금리",
        "Effective overnight U.S. interbank policy rate", _NY_FED, _NY_FED_URL,
        public_web=True,
    ),
    # New York Fed yield-curve model, collected from the research workbook by
    # the nyfed lane (not FRED). Dates mark the month being predicted, so the
    # newest observations sit up to twelve months in the future by design.
    FredSeriesSpec(
        "REC_PROB_12M", "recession_prob", "market", "미국 침체 확률 (12개월 선행)",
        "US recession odds (12M ahead)",
        "뉴욕 연은이 국채 10년–3개월 스프레드로 추정한 12개월 뒤 미국 침체 확률. 날짜는 예측 대상 월입니다",
        "Probability of a U.S. recession twelve months ahead, estimated by the New York Fed "
        "from the 10-year minus 3-month Treasury spread. Dates mark the predicted month",
        _NY_FED, _NY_FED_URL,
        public_web=True,
    ),
    # FOMC dot plot: the committee's own year-end fed-funds projections from the
    # quarterly Summary of Economic Projections. Annual series dated by the
    # projection target year, so observations legitimately sit in the future —
    # same forward-dating convention as `recession_prob`. The longer-run median
    # is dated by SEP release day instead, its latest value being current.
    FredSeriesSpec(
        "FEDTARMD", "fedfunds_proj_median", "rates", "연준 점도표 중앙값",
        "Fed dot plot median",
        "FOMC 위원들의 연말 기준금리 전망 중앙값(SEP). 날짜는 전망 대상 연도입니다",
        "Median of FOMC participants' year-end fed funds projections (SEP). "
        "Dates mark the projection target year", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FEDTARCTH", "fedfunds_proj_ct_high", "rates", "점도표 중앙경향 상단",
        "Dot plot central tendency, high",
        "SEP 기준금리 전망 중앙경향(상·하위 3명 제외)의 상단",
        "Upper bound of the SEP central tendency (trims the three highest and "
        "lowest projections)", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FEDTARCTL", "fedfunds_proj_ct_low", "rates", "점도표 중앙경향 하단",
        "Dot plot central tendency, low",
        "SEP 기준금리 전망 중앙경향(상·하위 3명 제외)의 하단",
        "Lower bound of the SEP central tendency (trims the three highest and "
        "lowest projections)", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FEDTARMDLR", "fedfunds_proj_longer_run", "rates", "점도표 장기 중앙값",
        "Dot plot longer-run median",
        "FOMC 위원들이 보는 장기(중립) 기준금리 전망의 중앙값. 날짜는 SEP 발표일입니다",
        "Median of FOMC participants' longer-run fed funds projections. "
        "Dates mark the SEP release day", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "IORB", "reserve_interest", "rates", "지급준비금 이자율",
        "Interest on Reserve Balances", "연준이 지급준비금에 적용하는 이자율",
        "Federal Reserve interest rate paid on reserve balances", _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "DCOILWTICO", "wti", "commodities", "WTI 원유", "WTI Crude Oil",
        "쿠싱 인도 기준 서부텍사스산 원유 현물가격", "Cushing, Oklahoma WTI spot crude oil price",
        "U.S. Energy Information Administration", "https://www.eia.gov/",
        public_web=True,
    ),
    FredSeriesSpec(
        "PCOPPUSDM", "copper", "commodities", "구리", "Copper",
        "국제통화기금이 집계한 월간 글로벌 구리 가격", "Monthly global copper price reported by the IMF",
        "International Monetary Fund", "https://www.imf.org/",
        public_web=False,
    ),
    # The Federal Reserve Board's own trade-weighted dollar indexes. The `dxy`
    # card above is ICE's index and stays license_required; these measure the
    # same idea on a different basket and base, so they are separate cards and
    # are never presented as DXY.
    FredSeriesSpec(
        "JRXWTFB_N.B", "dollar_index_broad", "fx", "광의 달러지수", "Broad Dollar Index",
        "연준이 교역량으로 가중한 광의 달러지수. ICE 달러지수(DXY)와 구성·기준이 달라 값을 비교할 수 없습니다",
        "The Federal Reserve's trade-weighted broad dollar index — a different basket and base from ICE's DXY, so the levels are not comparable",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "JRXWTFN_N.B", "dollar_index_afe", "fx", "선진국 달러지수", "AFE Dollar Index",
        "선진 교역상대국 통화 대비 달러의 교역가중 지수",
        "The dollar against advanced foreign economies, trade-weighted",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "JRXWTFO_N.B", "dollar_index_eme", "fx", "신흥국 달러지수", "EME Dollar Index",
        "신흥 교역상대국 통화 대비 달러의 교역가중 지수",
        "The dollar against emerging market economies, trade-weighted",
        _FED_BOARD, _FED_BOARD_URL,
        public_web=True,
    ),
    # Korean official closes, published as open data by the Financial Services
    # Commission. These are separate cards from the HIP-3 proxies `kospi`,
    # `kosdaq` and `samsung` on purpose: an exchange close in won and a synthetic
    # perpetual in USD are not the same measurement, so they never share a key
    # and are never spliced into one series.
    FredSeriesSpec(
        "FSC_KOSPI", "kospi_exact", "korea", "코스피 (공식 종가)", "KOSPI (official close)",
        "한국거래소 코스피 지수의 공식 종가. 다음 영업일에 공개되는 장 마감 기준값입니다",
        "The official Korea Exchange KOSPI close, published the next business day",
        _FSC, _FSC_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FSC_KOSDAQ", "kosdaq_exact", "korea", "코스닥 (공식 종가)", "KOSDAQ (official close)",
        "한국거래소 코스닥 지수의 공식 종가. 다음 영업일에 공개되는 장 마감 기준값입니다",
        "The official Korea Exchange KOSDAQ close, published the next business day",
        _FSC, _FSC_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FSC_005930", "samsung_exact", "korea", "삼성전자 (공식 종가)",
        "Samsung Electronics (official close)",
        "삼성전자 보통주의 원화 종가. USD 환산 합성 무기한선물과 다른 값입니다",
        "The Korean won close for Samsung Electronics common stock, not a USD synthetic",
        _FSC, _FSC_URL,
        public_web=True,
    ),
    FredSeriesSpec(
        "FSC_000660", "sk_hynix_exact", "korea", "SK하이닉스 (공식 종가)",
        "SK Hynix (official close)",
        "SK하이닉스 보통주의 원화 종가. USD 환산 합성 무기한선물과 다른 값입니다",
        "The Korean won close for SK Hynix common stock, not a USD synthetic",
        _FSC, _FSC_URL,
        public_web=True,
    ),
)
FRED_SERIES_BY_ID = {spec.series_id: spec for spec in FRED_SERIES}
FRED_SERIES_BY_KEY = {spec.key: spec for spec in FRED_SERIES}

# The rights verdict the catalog already encodes, restated in the vocabulary the
# neutral store uses. ``public_web=False`` on this catalog has always meant "the
# underlying data belongs to someone else" (Cboe, ICE, IMF), so it maps to
# license_required rather than a generic pending.
FRED_PROVIDER_ID = "fred"


def rights_status_for(spec: FredSeriesSpec) -> str:
    return "approved" if spec.public_web else "license_required"


class FredConfigurationError(DataError):
    """FRED was enabled without a usable API key."""


@dataclass(frozen=True)
class FredSeriesData:
    metadata: dict[str, Any]
    observations: tuple[tuple[dt.date, float], ...]


HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


class FredProvider:
    """Small, retrying FRED v1 JSON client with an injectable HTTP transport."""

    name = "fred"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        api_base: str = FRED_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise FredConfigurationError("FRED_API_KEY is required when FRED ingestion is enabled")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.api_base = api_base.rstrip("/")
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep

    def _request_json(self, endpoint: str, **params: Any) -> dict[str, Any]:
        query = urlencode({**params, "api_key": self.api_key, "file_type": "json"})
        request = Request(
            f"{self.api_base}/{endpoint.lstrip('/')}?{query}",
            headers={"Accept": "application/json", "User-Agent": "Mulmit/1.0"},
        )

        for attempt in range(self.retries + 1):
            try:
                raw = self._http_get(request, self.timeout)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("response root is not an object")
                if payload.get("error_code"):
                    code = int(payload["error_code"])
                    message = str(payload.get("error_message") or "FRED API error")
                    if code == 429:
                        raise RateLimited(message)
                    raise DataUnavailable(f"FRED API error {code}: {message}")
                return payload
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("FRED API rate limit exceeded") from exc
                raise DataUnavailable(f"FRED API HTTP error {exc.code} for {endpoint}") from exc
            except RateLimited:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise
            except DataUnavailable:
                raise
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError, ValueError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"Invalid or unavailable FRED response for {endpoint}") from exc

        raise AssertionError("unreachable")

    def fetch_metadata(self, series_id: str) -> dict[str, Any]:
        series_id = series_id.strip().upper()
        payload = self._request_json("series", series_id=series_id)
        rows = payload.get("seriess")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise DataUnavailable(f"FRED metadata is unavailable for {series_id}")
        metadata = dict(rows[0])
        if str(metadata.get("id", "")).upper() != series_id:
            raise DataUnavailable(f"FRED returned mismatched metadata for {series_id}")
        return metadata

    def fetch_observations(
        self,
        series_id: str,
        *,
        observation_start: dt.date | None = None,
    ) -> tuple[tuple[dt.date, float], ...]:
        series_id = series_id.strip().upper()
        params: dict[str, Any] = {
            "series_id": series_id,
            "sort_order": "asc",
            "limit": 100000,
        }
        if observation_start is not None:
            params["observation_start"] = observation_start.isoformat()
        payload = self._request_json("series/observations", **params)
        raw_rows = payload.get("observations")
        if not isinstance(raw_rows, list):
            raise DataUnavailable(f"FRED observations are unavailable for {series_id}")

        values: dict[dt.date, float] = {}
        for row in raw_rows:
            if not isinstance(row, dict) or row.get("value") in {None, "."}:
                continue
            try:
                date = dt.date.fromisoformat(str(row["date"]))
                value = float(row["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DataUnavailable(f"Malformed FRED observation for {series_id}") from exc
            if math.isfinite(value):
                values[date] = value

        observations = tuple(sorted(values.items()))
        if not observations:
            raise DataUnavailable(f"FRED has no numeric observations for {series_id}")
        return observations

    def fetch_release_dates(
        self, release_id: int, *, start: dt.date, end: dt.date, limit: int = 12
    ) -> list[str]:
        """한 릴리스의 (예정 포함) 발표일 목록. 경제 캘린더가 쓴다."""
        payload = self._request_json(
            "release/dates",
            release_id=release_id,
            realtime_start=start.isoformat(),
            realtime_end=end.isoformat(),
            include_release_dates_with_no_data="true",
            sort_order="asc",
            limit=limit,
        )
        rows = payload.get("release_dates")
        if not isinstance(rows, list):
            raise DataUnavailable(f"FRED release dates unavailable for {release_id}")
        return [str(row.get("date")) for row in rows if isinstance(row, dict) and row.get("date")]

    def fetch_series(self, series_id: str) -> FredSeriesData:
        return FredSeriesData(
            metadata=self.fetch_metadata(series_id),
            observations=self.fetch_observations(series_id),
        )
