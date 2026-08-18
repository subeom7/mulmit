"""금융감독원 Open DART — 임원·주요주주 특정증권등 소유상황 보고.

미국 SEC EDGAR lane의 한국 대응물이다. DART는 자본시장법상 법정 공시를 담는
공공기관의 전자공시시스템이고, Open DART는 그것을 "누구나 활용"하도록 연 API다.
이용약관(2026-08-17 확인)은 재배포를 금지하는 조항 없이 다음을 둔다:

* 제10조 ④ — 이용횟수 허용량 제한이 있으며 홈페이지에 게시한다
* 제16조 ① — 오픈API **서비스 및 관련 프로그램**의 저작권은 금융감독원에 있다
  (공시정보 자체가 아니라 서비스·프로그램에 대한 조항이다)
* 제23조 — 공시정보는 제출인 책임으로 작성되며 정확성·완전성을 보장하지 않는다

EDGAR와 같은 원칙으로 다룬다: 보고된 값을 **가공 없이 전달**하고, 출처와 원문
링크를 값과 함께 싣는다. 주의할 차이 — elestock은 **보고서 단위**의 소유수량과
순증감이며, Form 4처럼 개별 거래(매수/매도·단가)가 아니다. 화면 문구도 그렇게
말해야 한다.

키는 opendart.fss.or.kr에서 배포별로 발급받으며 커밋하지 않는다. 요청 한도는
키 단위로 계량되므로 스로틀을 두고, 조회는 캐시 미스에서만 일어난다.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from collections.abc import Callable
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .base import DataError, DataUnavailable, RateLimited

DART_API_BASE = "https://opendart.fss.or.kr/api"
DART_PROVIDER_ID = "dart"
DART_PUBLISHER = "금융감독원"
DART_PUBLISHER_EN = "Financial Supervisory Service"
DART_PUBLISHER_URL = "https://dart.fss.or.kr/"
DART_TERMS_URL = "https://opendart.fss.or.kr/intro/terms.do"
DART_ATTRIBUTION = "출처: 금융감독원 전자공시시스템(DART)"
DART_ATTRIBUTION_EN = "Source: Financial Supervisory Service DART."

# 공시 원문 뷰어. rcept_no 하나면 사람이 읽는 화면으로 간다.
DART_REPORT_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

STATUS_OK = "000"
STATUS_NO_DATA = "013"
_RATE_LIMIT_STATUSES = frozenset({"020", "021"})
_KEY_STATUSES = frozenset({"010", "011", "012", "800"})

HttpGet = Callable[[Request, float], bytes]


class DartAuthorizationError(DataError):
    """키가 없거나, 만료됐거나, 정지된 상태다."""


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _parse_int(value: Any) -> int | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


class DartProvider:
    """Open DART의 네 endpoint만 아는 작은 클라이언트."""

    name = DART_PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.25,
        api_base: str = DART_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key.strip():
            raise DartAuthorizationError("DART_API_KEY is required (opendart.fss.or.kr)")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.request_interval = max(0.0, float(request_interval))
        self.api_base = api_base.rstrip("/")
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request = 0.0

    def _throttle(self) -> None:
        if self.request_interval <= 0:
            return
        elapsed = self._monotonic() - self._last_request
        if 0 <= elapsed < self.request_interval:
            self._sleep(self.request_interval - elapsed)
        self._last_request = self._monotonic()

    def _get_bytes(self, endpoint: str, params: dict[str, str]) -> bytes:
        query = urlencode({"crtfc_key": self.api_key, **params})
        request = Request(
            f"{self.api_base}/{endpoint}?{query}",
            headers={"Accept": "*/*", "User-Agent": "Mulmit/1.0"},
            method="GET",
        )
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                return self._http_get(request, self.timeout)
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("DART throttled the request") from exc
                raise DataUnavailable(f"DART HTTP error {exc.code} for {endpoint}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"DART unreachable for {endpoint}") from exc
        raise AssertionError("unreachable")

    def _check_status(self, status: str, message: str) -> None:
        if status in (STATUS_OK, STATUS_NO_DATA):
            return
        if status in _RATE_LIMIT_STATUSES:
            raise RateLimited(f"DART request allowance exhausted ({status}: {message})")
        if status in _KEY_STATUSES:
            raise DartAuthorizationError(f"DART rejected the key ({status}: {message})")
        raise DataUnavailable(f"DART returned status {status}: {message}")

    def fetch_corp_codes(self) -> list[dict[str, Any]]:
        """상장사만 담은 (종목코드 → 법인코드) 매핑.

        corpCode.xml은 비상장 포함 10만여 법인을 담은 zip이다. 오류 응답은 zip이
        아니라 JSON/XML 본문으로 오므로, zip 시그니처가 아니면 상태를 해석한다.
        """
        raw = self._get_bytes("corpCode.xml", {})
        if not raw.startswith(b"PK"):
            try:
                body = json.loads(raw.decode("utf-8"))
                self._check_status(str(body.get("status")), str(body.get("message")))
            except (JSONDecodeError, UnicodeDecodeError):
                pass
            raise DataUnavailable("DART corpCode response is not a zip archive")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                inner = archive.read("CORPCODE.xml")
            root = ElementTree.fromstring(inner)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise DataUnavailable("DART corpCode archive is unreadable") from exc

        rows = []
        for node in root.iter("list"):
            stock = (node.findtext("stock_code") or "").strip()
            if not stock:
                continue  # 비상장 법인은 매핑 대상이 아니다
            rows.append({
                "stock_code": stock,
                "corp_code": (node.findtext("corp_code") or "").strip(),
                "corp_name": (node.findtext("corp_name") or "").strip(),
                "modify_date": (node.findtext("modify_date") or "").strip(),
            })
        if not rows:
            raise DataUnavailable("DART corpCode parsed to zero listed companies")
        return rows

    def _get_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        raw = self._get_bytes(endpoint, params)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError) as exc:
            raise DataUnavailable(f"DART {endpoint} response is not JSON") from exc
        if not isinstance(body, dict):
            raise DataUnavailable(f"DART {endpoint} response is not an object")
        self._check_status(str(body.get("status") or ""), str(body.get("message") or ""))
        return body

    def fetch_filing_index(
        self, *, detail_type: str, bgn_de: str, end_de: str, max_pages: int = 60
    ) -> tuple[list[dict[str, Any]], bool]:
        """공시검색(list.json)을 기간·상세유형으로 걷는다.

        제출인 필터가 없어 기간 안의 전 페이지를 받아야 한다. 최신순 정렬이
        기본값이므로 ``max_pages``에서 끊기면 잘리는 쪽은 가장 오래된
        공시들이고, 두 번째 반환값이 그 사실을 알린다.
        """
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            body = self._get_json(
                "list.json",
                {
                    "pblntf_detail_ty": detail_type,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "page_no": str(page),
                    "page_count": "100",
                },
            )
            if str(body.get("status") or "") == STATUS_NO_DATA:
                return rows, False
            for row in body.get("list") or []:
                if not isinstance(row, dict):
                    continue
                rcept_no = str(row.get("rcept_no") or "").strip()
                if not rcept_no:
                    continue
                rows.append({
                    "rcept_no": rcept_no,
                    "rcept_dt": str(row.get("rcept_dt") or "").strip(),
                    "corp_code": str(row.get("corp_code") or "").strip(),
                    "corp_name": str(row.get("corp_name") or "").strip(),
                    "stock_code": str(row.get("stock_code") or "").strip(),
                    "corp_cls": str(row.get("corp_cls") or "").strip(),
                    "report_nm": str(row.get("report_nm") or "").strip(),
                    "flr_nm": str(row.get("flr_nm") or "").strip(),
                })
            total_page = int(body.get("total_page") or 1)
            if page >= total_page:
                return rows, False
            if page >= max_pages:
                return rows, True
            page += 1

    def fetch_major_holdings(self, corp_code: str) -> list[dict[str, Any]]:
        """대량보유(5%) 상황보고 목록(majorstock.json). 보고서 단위 값이다."""
        body = self._get_json("majorstock.json", {"corp_code": corp_code.strip()})
        if str(body.get("status") or "") == STATUS_NO_DATA:
            return []
        holdings = []
        for row in body.get("list") or []:
            if not isinstance(row, dict):
                continue
            rcept_no = str(row.get("rcept_no") or "").strip()
            if not rcept_no:
                continue
            holdings.append({
                "rcept_no": rcept_no,
                # list.json은 YYYYMMDD, majorstock은 YYYY-MM-DD로 온다.
                "report_date": str(row.get("rcept_dt") or "").strip(),
                "report_type": str(row.get("report_tp") or "").strip(),
                "reporter": str(row.get("repror") or "").strip(),
                "shares": _parse_int(row.get("stkqy")),
                "shares_change": _parse_int(row.get("stkqy_irds")),
                "ratio": _parse_float(row.get("stkrt")),
                "ratio_change": _parse_float(row.get("stkrt_irds")),
                "reason": str(row.get("report_resn") or "").strip(),
                "report_url": DART_REPORT_URL.format(rcept_no=rcept_no),
            })
        return holdings

    def fetch_ownership_reports(self, corp_code: str) -> list[dict[str, Any]]:
        """임원·주요주주 소유상황 보고 목록. 보고서 단위이며 거래 단위가 아니다."""
        body = self._get_json("elestock.json", {"corp_code": corp_code.strip()})
        if str(body.get("status") or "") == STATUS_NO_DATA:
            return []

        reports = []
        for row in body.get("list") or []:
            if not isinstance(row, dict):
                continue
            rcept_no = str(row.get("rcept_no") or "").strip()
            if not rcept_no:
                continue
            reports.append({
                "rcept_no": rcept_no,
                "report_date": str(row.get("rcept_dt") or "").strip(),
                "reporter": str(row.get("repror") or "").strip(),
                "executive_status": str(row.get("isu_exctv_rgist_at") or "").strip(),
                "position": str(row.get("isu_exctv_ofcps") or "").strip(),
                "main_shareholder": str(row.get("isu_main_shrholdr") or "").strip(),
                "shares_owned": _parse_int(row.get("sp_stock_lmp_cnt")),
                "shares_change": _parse_int(row.get("sp_stock_lmp_irds_cnt")),
                "ownership_ratio": _parse_float(row.get("sp_stock_lmp_rate")),
                "ratio_change": _parse_float(row.get("sp_stock_lmp_irds_rate")),
                "report_url": DART_REPORT_URL.format(rcept_no=rcept_no),
            })
        return reports
