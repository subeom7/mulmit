"""SEC EDGAR ownership-filing (Form 3/4/5) client.

EDGAR is a public federal disclosure system: the SEC states that anyone can
access and download the filings for free, and US government works carry no
copyright. What EDGAR does impose is operational, and both rules are enforced
here rather than left to the caller:

* every request declares a User-Agent carrying a real contact address
* requests are spaced so the published 10 requests/second cap is never
  approached, counted across the whole process

https://www.sec.gov/os/accessing-edgar-data

Only :mod:`app.ingest` constructs this. Request handlers read the database.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .base import DataError, DataUnavailable, RateLimited


class EdgarNotFound(DataUnavailable):
    """The requested EDGAR document or XBRL concept does not exist (404)."""

SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
COMPANY_TICKERS_URL = f"{SEC_BASE}/files/company_tickers.json"
EDGAR_TERMS_URL = f"{SEC_BASE}/os/accessing-edgar-data"
SEC_PUBLISHER = "U.S. Securities and Exchange Commission"
SEC_PUBLISHER_URL = f"{SEC_BASE}/"
SEC_RIGHTS_NOTICE = (
    "EDGAR filings are public U.S. federal disclosure records. Mulmit relays the "
    "filed figures without adjustment and does not interpret them as trading advice."
)
SEC_RIGHTS_NOTICE_KO = (
    "EDGAR 공시는 미국 연방정부가 공개하는 공시 원문입니다. Mulmit은 공시된 값을 "
    "가공 없이 전달하며 투자 판단이나 권유로 해석하지 않습니다."
)

# Forms 3/4/5 are the ownership set. Form 4 carries the individual transactions;
# 3 is the initial statement and 5 the annual catch-up.
OWNERSHIP_FORMS = ("3", "4", "5")

# Official Form 345 transaction codes. Kept verbatim: an award (A) is not an
# open-market purchase (P) and must never be summed with one.
TRANSACTION_CODES: dict[str, tuple[str, str]] = {
    "P": ("Open-market or private purchase", "시장 내·외 매수"),
    "S": ("Open-market or private sale", "시장 내·외 매도"),
    "A": ("Grant, award or other acquisition from the issuer", "발행사로부터의 부여·수령"),
    "D": ("Disposition to the issuer", "발행사에 대한 처분"),
    "F": ("Shares withheld to satisfy tax withholding", "세금 원천징수용 주식 상계"),
    "M": ("Exercise or conversion of a derivative security", "파생 증권 행사·전환"),
    "C": ("Conversion of a derivative security", "파생 증권 전환"),
    "E": ("Expiration of a short derivative position", "숏 파생 포지션 만료"),
    "H": ("Expiration of a long derivative position", "롱 파생 포지션 만료"),
    "G": ("Bona fide gift", "증여"),
    "L": ("Small acquisition", "소규모 취득"),
    "W": ("Acquisition or disposition by will or laws of descent", "상속·유증에 따른 취득·처분"),
    "X": ("Exercise of an in-the-money or at-the-money derivative", "내가격·등가격 파생 행사"),
    "I": ("Discretionary transaction", "재량 거래"),
    "J": ("Other acquisition or disposition", "기타 취득·처분"),
    "K": ("Equity swap or similar instrument", "주식 스왑 등"),
    "U": ("Disposition pursuant to a tender of shares", "공개매수 응모에 따른 처분"),
}


class SecEdgarConfigurationError(DataError):
    """SEC EDGAR was enabled without a declared contact User-Agent."""


@dataclass(frozen=True)
class InsiderTransaction:
    """One reported line of a Form 3/4/5 filing."""

    accession_number: str
    sequence: int
    form_type: str
    filing_date: dt.date
    transaction_date: dt.date | None
    owner_name: str
    owner_cik: str
    owner_title: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    security_title: str
    transaction_code: str
    acquired_disposed: str
    is_derivative: bool
    shares: float | None
    price_per_share: float | None
    shares_owned_after: float | None
    direct_or_indirect: str
    filing_url: str


# 8-K 이벤트 공시. submissions 응답에 이미 들어 있는 행이라 추가 요청이 없다.
EVENT_FORMS = ("8-K", "8-K/A")
EVENT_LIMIT = 15

# 공식 8-K Item 번호와 제목의 닫힌 매핑. 여기 없는 번호는 원문 코드 그대로 나간다.
EVENT_ITEM_LABELS: dict[str, tuple[str, str]] = {
    "1.01": ("Entry into a material agreement", "중요 계약 체결"),
    "1.02": ("Termination of a material agreement", "중요 계약 해지"),
    "1.03": ("Bankruptcy or receivership", "파산·법정관리"),
    "2.01": ("Completed acquisition or disposition of assets", "자산 취득·처분 완료"),
    "2.02": ("Results of operations", "실적 발표"),
    "2.03": ("Creation of a direct financial obligation", "채무 부담"),
    "2.04": ("Triggering events on financial obligations", "채무 조기상환 사유 발생"),
    "2.05": ("Costs associated with exit or disposal activities", "구조조정 비용"),
    "2.06": ("Material impairments", "자산 손상"),
    "3.01": ("Delisting or listing-standard notice", "상장 유지 관련 통지"),
    "3.02": ("Unregistered sales of equity securities", "미등록 증권 발행"),
    "3.03": ("Material modification to rights of security holders", "증권 권리 변경"),
    "4.01": ("Change in certifying accountant", "감사인 변경"),
    "4.02": ("Non-reliance on previously issued financials", "기존 재무제표 신뢰 불가"),
    "5.01": ("Change in control", "지배권 변동"),
    "5.02": ("Officer or director change", "임원·이사 변동"),
    "5.03": ("Amendments to charter or bylaws", "정관 변경"),
    "5.07": ("Submission of matters to a vote", "주주총회 결과"),
    "5.08": ("Shareholder director nominations", "주주 이사 후보 추천"),
    "7.01": ("Regulation FD disclosure", "Reg FD 공시"),
    "8.01": ("Other events", "기타 중요 이벤트"),
    "9.01": ("Financial statements and exhibits", "재무제표·첨부"),
}


@dataclass(frozen=True)
class CompanyEvent:
    """One 8-K row straight out of the submissions index."""

    accession_number: str
    form_type: str
    filed_at: dt.date
    accepted_at: str | None
    items: str
    url: str


@dataclass(frozen=True)
class CompanyFilings:
    cik: str
    name: str
    exchanges: tuple[str, ...] = ()
    transactions: tuple[InsiderTransaction, ...] = field(default=())
    filings_seen: int = 0
    events: tuple[CompanyEvent, ...] = field(default=())


HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    """Fetch and decode the body.

    The SEC's fair-access guidance asks callers to minimise server load, so the
    requests advertise compression. ``urllib`` does not transparently decode it,
    and the transport seam only passes bytes, so unwrapping belongs here.
    """
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS bases
        raw = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)  # raw deflate, no zlib header
    return raw


def _text(node: ElementTree.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _number(node: ElementTree.Element | None, path: str) -> float | None:
    raw = _text(node, path)
    if not raw:
        return None
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _flag(node: ElementTree.Element | None, path: str) -> bool:
    return _text(node, path).strip().lower() in {"1", "true", "yes"}


def _date(raw: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(raw.strip()[:10])
    except (AttributeError, ValueError):
        return None


def normalize_cik(value: Any) -> str:
    """EDGAR paths need the bare integer; the JSON API needs it zero-padded."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        raise DataUnavailable(f"unusable CIK: {value!r}")
    return str(int(digits))


def transaction_code_label(code: str) -> dict[str, str]:
    known = TRANSACTION_CODES.get(code.strip().upper())
    if known is None:
        return {"en": f"Code {code}" if code else "Unspecified", "ko": f"코드 {code}" if code else "미지정"}
    return {"en": known[0], "ko": known[1]}


# --- 13F-HR 기관 보유 ---------------------------------------------------------
#
# 13F는 운용자산 1억 달러 이상인 기관이 분기마다 미국 상장주식 롱 포지션을
# 신고하는 서식이다. **분기 말 기준이고 45일 안에 내면 되므로** 화면에 뜨는
# 것은 최대 한 분기 반쯤 지난 사진이다.
#
# 이 서식으로 만들 수 없는 것을 먼저 적어 둔다 — 공매도, 채권, 현금, 해외
# 상장 주식, 사모 지분은 들어오지 않는다. 그래서 여기서 나온 파이는 "그 사람의
# 자산 전부"가 아니라 **"미국 상장주식 롱 포지션의 구성"** 이다.

#: 13F 신고 의무가 생기는 운용자산 기준선. 아래 단위 판별에 쓴다.
FORM_13F_THRESHOLD_USD = 100_000_000

FORM_13F = ("13F-HR", "13F-HR/A")


@dataclass(frozen=True)
class ManagerHolding:
    issuer: str
    cusip: str
    value_usd: float
    shares: float | None
    is_option: bool


@dataclass(frozen=True)
class ManagerPortfolio:
    cik: str
    name: str
    form: str
    filed: dt.date | None
    period: dt.date | None
    accession: str
    holdings: tuple[ManagerHolding, ...]
    row_count: int
    value_scale: str
    options_value_usd: float

    @property
    def total_usd(self) -> float:
        return sum(holding.value_usd for holding in self.holdings)


def _local(tag: str) -> str:
    """네임스페이스 접두어를 뗀 태그 이름.

    13F 정보표는 제출 대행사마다 접두어가 다르다(`ns1:infoTable`, `infoTable`,
    `ns:infoTable`). 접두어를 그대로 찾으면 어떤 제출자는 조용히 0건이 된다 —
    실제로 처음 훑을 때 브리지워터·피셔가 그렇게 빠졌다.
    """
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _parse_info_table(
    blocks: list[ElementTree.Element],
) -> tuple[tuple[ManagerHolding, ...], int, float]:
    """행을 **CUSIP 단위로 합친다.**

    한 종목이 여러 행으로 쪼개져 오는 제출자가 있다 — 운용 재량(sole/shared)
    구분이나 계좌 구분 때문이다. 버크셔의 최근 제출은 89행이지만 종목은
    26개뿐이다(실측 2026-08-24). 합치지 않으면 애플이 파이에 여러 조각으로
    나타난다.

    **키를 이름에서 CUSIP으로 바꿨다(2026-08-25).** 이름으로 묶으면 같은 분기
    안에서는 맞아떨어지지만 **분기를 견줄 때 무너진다** — 신고자가 표기를
    바꾸기 때문이다. 실측으로 버크셔가 `BANK AMERICA CORP`를 `BANK OF AMER
    CORP`로, `CHUBB LTD SWITZ`를 `CHUBB LIMITED`로 바꿔 적었고, 이름으로
    맞추면 **275억 달러어치를 전량 매도하고 같은 분기에 새로 샀다**는 그림이
    나온다. 피셔도 같다(`JDCOM INC ADR` -> `JD COM INC ADR`). CUSIP은 그런
    표기 변경을 타지 않는다.

    표시할 이름은 그 분기의 신고에 적힌 것을 그대로 쓴다 — 우리가 고르지 않는다.
    """
    merged: dict[str, dict[str, Any]] = {}
    options_value = 0.0

    for block in blocks:
        fields: dict[str, str] = {}
        for node in block.iter():
            name = _local(node.tag)
            if name in {"nameOfIssuer", "cusip", "value", "sshPrnamt", "putCall"}:
                fields[name] = (node.text or "").strip()

        issuer = " ".join(fields.get("nameOfIssuer", "").split()).upper()
        cusip = fields.get("cusip", "").strip().upper()
        if not issuer:
            continue
        # CUSIP이 비면 이름으로 떨어진다 — 합치기라도 해야 파이가 쪼개지지 않는다.
        key = cusip or issuer
        try:
            value = float(fields.get("value", "") or 0)
        except ValueError:
            value = 0.0
        try:
            shares = float(fields.get("sshPrnamt", "") or 0) or None
        except ValueError:
            shares = None

        is_option = bool(fields.get("putCall"))
        if is_option:
            options_value += value

        row = merged.setdefault(
            key,
            {"issuer": issuer, "cusip": cusip, "value": 0.0,
             "shares": 0.0, "is_option": False},
        )
        row["value"] += value
        if shares:
            row["shares"] += shares
        row["is_option"] = row["is_option"] or is_option

    holdings = tuple(
        ManagerHolding(
            issuer=row["issuer"],
            cusip=row["cusip"],
            value_usd=row["value"],
            shares=row["shares"] or None,
            is_option=row["is_option"],
        )
        for row in sorted(merged.values(), key=lambda row: -row["value"])
    )
    return holdings, len(blocks), options_value


def _normalise_scale(
    holdings: tuple[ManagerHolding, ...], options_value: float
) -> tuple[str, tuple[ManagerHolding, ...], float]:
    """금액 단위를 맞춘다 — **제출자마다 다르다.**

    2023년 개정으로 `value`는 달러가 됐지만 여전히 **천 달러**로 내는 제출자가
    있다. 실측(2026-08-24): 버크셔 합계 2.99e11(달러 = $299B), 두케인 합계
    5.21e6. 두케인이 달러라면 $5.2M인데, **13F는 1억 달러 이상일 때만 의무**라
    있을 수 없는 값이다. 즉 두케인은 천 단위다.

    그래서 판별 규칙을 서식의 기준선 자체에서 가져온다 — **합계가 1억 달러에
    못 미치면 그 숫자는 달러가 아니다.** 섞어서 한 화면에 올리면 조용히 천 배
    틀린 그림이 나오므로, 추정이 아니라 규칙으로 못 박는다.
    """
    total = sum(holding.value_usd for holding in holdings)
    if total <= 0 or total >= FORM_13F_THRESHOLD_USD:
        return "dollars", holdings, options_value
    scaled = tuple(
        ManagerHolding(
            issuer=holding.issuer,
            cusip=holding.cusip,
            value_usd=holding.value_usd * 1000,
            shares=holding.shares,
            is_option=holding.is_option,
        )
        for holding in holdings
    )
    return "thousands", scaled, options_value * 1000


class SecEdgarProvider:
    """Rate-limited EDGAR reader with an injectable HTTP transport."""

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.15,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        user_agent = user_agent.strip()
        if "@" not in user_agent:
            # The SEC asks for "Sample Company Name AdminContact@domain.com".
            # A User-Agent without a contact address is exactly what their fair
            # access policy treats as an unclassified bot.
            raise SecEdgarConfigurationError(
                "SEC_EDGAR_USER_AGENT must declare a contact email address, "
                "for example 'Mulmit admin@example.com'"
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.request_interval = max(0.0, request_interval)
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._throttle_lock = threading.Lock()

    # --- transport ----------------------------------------------------------

    def _throttle(self) -> None:
        """Space requests process-wide; the SEC counts per user, not per socket."""
        if not self.request_interval:
            return
        with self._throttle_lock:
            now = self._monotonic()
            if self._last_request_at is not None:
                waiting = self.request_interval - (now - self._last_request_at)
                if waiting > 0:
                    self._sleep(waiting)
                    now = self._monotonic()
            self._last_request_at = now

    def _request(self, url: str, *, accept: str) -> bytes:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                return self._http_get(request, self.timeout)
            except HTTPError as exc:
                if exc.code == 404:
                    # 개념 사다리(fundamentals)가 "없는 태그"와 "장애"를 구분해야
                    # 하므로 404는 하위 타입으로 던진다.
                    raise EdgarNotFound(f"EDGAR has no document at {url}") from exc
                retryable = exc.code in {403, 429} or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code in {403, 429}:
                    # EDGAR answers a fair-access block with 403, not only 429.
                    raise RateLimited(f"EDGAR throttled the request ({exc.code})") from exc
                raise DataUnavailable(f"EDGAR HTTP error {exc.code} for {url}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"EDGAR is unreachable: {url}") from exc
        raise AssertionError("unreachable")

    def _request_json(self, url: str) -> Any:
        raw = self._request(url, accept="application/json")
        try:
            return json.loads(raw.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError) as exc:
            raise DataUnavailable(f"EDGAR returned invalid JSON for {url}") from exc

    def _request_xml(self, url: str) -> ElementTree.Element:
        raw = self._request(url, accept="application/xml")
        try:
            return ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise DataUnavailable(f"EDGAR returned invalid XML for {url}") from exc

    # --- endpoints ----------------------------------------------------------

    def fetch_ticker_map(self) -> dict[str, tuple[str, str]]:
        """``{TICKER: (cik, company name)}`` for every exchange-listed filer."""
        payload = self._request_json(COMPANY_TICKERS_URL)
        if not isinstance(payload, dict):
            raise DataUnavailable("EDGAR ticker map is not an object")
        mapping: dict[str, tuple[str, str]] = {}
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker or row.get("cik_str") is None:
                continue
            mapping[ticker] = (normalize_cik(row["cik_str"]), str(row.get("title") or ticker))
        if not mapping:
            raise DataUnavailable("EDGAR ticker map is empty")
        return mapping

    def fetch_company_concept(
        self, cik: str, tag: str, *, taxonomy: str = "us-gaap"
    ) -> dict[str, Any]:
        """One XBRL concept's reported values across a company's filings.

        존재하지 않는 태그는 :class:`EdgarNotFound`로 온다 — 회사마다 쓰는
        태그가 달라 호출자가 사다리로 시도한다.
        """
        url = (
            f"{SEC_DATA_BASE}/api/xbrl/companyconcept/"
            f"CIK{int(cik):010d}/{taxonomy}/{tag}.json"
        )
        payload = self._request_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("units"), dict):
            raise DataUnavailable(f"EDGAR concept response malformed for {tag}")
        return payload

    def fetch_company_facts(self, cik: str) -> dict[str, Any]:
        """회사의 전체 XBRL 팩트 한 파일 — companyconcept의 폴백 경로.

        EDGAR 두 엔드포인트가 불일치하는 회사가 있다(실측 2026-08-20: KO의
        Revenues가 companyconcept에선 200 + 빈 USD 배열, companyfacts에는
        연간 24행). 태그가 아니라 경로를 갈아타야 하는 경우다.
        """
        url = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
        payload = self._request_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
            raise DataUnavailable(f"EDGAR companyfacts malformed for CIK {cik}")
        return payload

    def fetch_company(self, cik: str, *, form_limit: int = 40) -> CompanyFilings:
        """Company metadata plus parsed transactions from its recent Form 3/4/5s."""
        cik = normalize_cik(cik)
        payload = self._request_json(f"{SEC_DATA_BASE}/submissions/CIK{int(cik):010d}.json")
        if not isinstance(payload, dict):
            raise DataUnavailable(f"EDGAR submissions for CIK {cik} is not an object")

        recent = (payload.get("filings") or {}).get("recent") or {}
        forms = recent.get("form")
        if not isinstance(forms, list):
            raise DataUnavailable(f"EDGAR submissions for CIK {cik} has no recent filings")

        accessions = recent.get("accessionNumber") or []
        filing_dates = recent.get("filingDate") or []
        documents = recent.get("primaryDocument") or []
        acceptance_times = recent.get("acceptanceDateTime") or []
        item_lists = recent.get("items") or []

        # 8-K 행은 같은 응답에서 그대로 뽑는다 — 이 피드를 위한 추가 요청은 없다.
        events: list[CompanyEvent] = []
        for index, form in enumerate(forms):
            if len(events) >= EVENT_LIMIT:
                break
            if str(form).strip() not in EVENT_FORMS:
                continue
            try:
                accession = str(accessions[index])
                filed_at = _date(str(filing_dates[index]))
                document = str(documents[index] or "")
            except (IndexError, TypeError):
                continue
            if not accession or filed_at is None:
                continue
            accepted = str(acceptance_times[index]) if index < len(acceptance_times) else ""
            items = str(item_lists[index]) if index < len(item_lists) else ""
            bare = accession.replace("-", "")
            url = (
                f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{bare}/{document}"
                if document
                else f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{bare}"
            )
            events.append(CompanyEvent(
                accession_number=accession,
                form_type=str(form).strip(),
                filed_at=filed_at,
                accepted_at=accepted or None,
                items=items,
                url=url,
            ))

        transactions: list[InsiderTransaction] = []
        seen = 0
        for index, form in enumerate(forms):
            if seen >= form_limit:
                break
            if str(form).strip() not in OWNERSHIP_FORMS:
                continue
            try:
                accession = str(accessions[index])
                filing_date = _date(str(filing_dates[index]))
                document = str(documents[index])
            except (IndexError, TypeError):
                continue
            if filing_date is None:
                continue
            seen += 1
            try:
                transactions.extend(
                    self.fetch_ownership_document(
                        cik,
                        accession,
                        document,
                        form_type=str(form).strip(),
                        filing_date=filing_date,
                    )
                )
            except DataUnavailable:
                # One unreadable filing must not discard the rest of the history.
                continue

        exchanges = payload.get("exchanges")
        return CompanyFilings(
            cik=cik,
            name=str(payload.get("name") or cik),
            exchanges=tuple(str(item) for item in exchanges) if isinstance(exchanges, list) else (),
            transactions=tuple(transactions),
            filings_seen=seen,
            events=tuple(events),
        )

    def fetch_ownership_document(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
        *,
        form_type: str,
        filing_date: dt.date,
    ) -> list[InsiderTransaction]:
        """Parse one ownership filing into its reported lines.

        ``primaryDocument`` points at the XSL-rendered HTML view
        (``xslF345X06/form4.xml``); the machine-readable original sits beside it
        in the same folder, so the styling directory is stripped.
        """
        cik = normalize_cik(cik)
        bare_accession = accession_number.replace("-", "")
        document = primary_document.rsplit("/", 1)[-1]
        folder = f"{SEC_BASE}/Archives/edgar/data/{cik}/{bare_accession}"
        url = f"{folder}/{document}"
        root = self._request_xml(url)

        # The link a person clicks is not the file the parser reads. The raw
        # XML renders as an unstyled document tree in a browser, so the stored
        # URL prefers the XSL-rendered view EDGAR itself points at, and falls
        # back to the filing index page when a filing has no styled twin.
        if "/" in primary_document:
            display_url = f"{folder}/{primary_document}"
        elif document.endswith(".xml"):
            display_url = f"{folder}/{accession_number}-index.htm"
        else:
            display_url = url

        owner = root.find("reportingOwner")
        relationship = owner.find("reportingOwnerRelationship") if owner is not None else None
        owner_name = _text(owner, "reportingOwnerId/rptOwnerName")
        owner_cik_raw = _text(owner, "reportingOwnerId/rptOwnerCik")
        common = {
            "accession_number": accession_number,
            "form_type": form_type,
            "filing_date": filing_date,
            "owner_name": owner_name or "(undisclosed)",
            "owner_cik": owner_cik_raw.strip() or "",
            "owner_title": _text(relationship, "officerTitle") or _text(relationship, "otherText"),
            "is_director": _flag(relationship, "isDirector"),
            "is_officer": _flag(relationship, "isOfficer"),
            "is_ten_percent_owner": _flag(relationship, "isTenPercentOwner"),
            "filing_url": display_url,
        }

        rows: list[InsiderTransaction] = []
        for tag, derivative in (("nonDerivativeTransaction", False), ("derivativeTransaction", True)):
            for node in root.iter(tag):
                rows.append(
                    InsiderTransaction(
                        sequence=len(rows),
                        transaction_date=_date(_text(node, "transactionDate/value")),
                        security_title=_text(node, "securityTitle/value"),
                        transaction_code=_text(node, "transactionCoding/transactionCode").upper(),
                        acquired_disposed=_text(
                            node, "transactionAmounts/transactionAcquiredDisposedCode/value"
                        ).upper(),
                        is_derivative=derivative,
                        shares=_number(node, "transactionAmounts/transactionShares/value"),
                        price_per_share=_number(
                            node, "transactionAmounts/transactionPricePerShare/value"
                        ),
                        shares_owned_after=_number(
                            node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
                        ),
                        direct_or_indirect=_text(
                            node, "ownershipNature/directOrIndirectOwnership/value"
                        ).upper(),
                        **common,
                    )
                )
        return rows

    def fetch_latest_13f(self, cik: str) -> ManagerPortfolio:
        return self.fetch_recent_13f(cik, limit=1)[0]

    def fetch_recent_13f(self, cik: str, *, limit: int = 2) -> tuple[ManagerPortfolio, ...]:
        """최근 분기부터 `limit`개를 최신순으로 읽는다.

        **정정 신고를 올바로 다루는 것이 여기의 요점이다.** 13F-HR/A는 같은
        분기를 다시 낸 것이라, 제출 순서대로 두 개를 집으면 **같은 분기를 서로
        빼게 되어 변화가 0으로 나온다**. 그래서 분기(reportDate)로 묶고 분기마다
        **가장 최근에 제출된 것** 하나만 쓴다 — 정정이 있으면 정정본이 이긴다.
        """
        cik = normalize_cik(cik)
        payload = self._request_json(f"{SEC_DATA_BASE}/submissions/CIK{int(cik):010d}.json")
        if not isinstance(payload, dict):
            raise DataUnavailable(f"EDGAR submissions for CIK {cik} is not an object")

        recent = (payload.get("filings") or {}).get("recent") or {}
        forms = recent.get("form")
        if not isinstance(forms, list):
            raise DataUnavailable(f"EDGAR submissions for CIK {cik} has no recent filings")

        accessions = recent.get("accessionNumber") or []
        filed_dates = recent.get("filingDate") or []
        periods = recent.get("reportDate") or []

        # 분기별로 첫 등장(=가장 최근 제출)만 남긴다. `recent`는 최신순이다.
        chosen: list[tuple[str, str, str, str]] = []
        seen: set[str] = set()
        for index, form in enumerate(forms):
            if form not in FORM_13F:
                continue
            period = str(periods[index] if index < len(periods) else "")
            if not period or period in seen:
                continue
            seen.add(period)
            chosen.append((
                str(form), str(filed_dates[index]), period,
                str(accessions[index]).replace("-", ""),
            ))
            if len(chosen) >= limit:
                break

        if not chosen:
            raise EdgarNotFound(f"CIK {cik} has no recent 13F-HR")

        built: list[ManagerPortfolio] = []
        for form, filed, period, accession in chosen:
            holdings, rows, options = self._fetch_13f_table(cik, accession)
            if not holdings:
                if built:
                    # 최신 분기는 읽혔는데 직전 분기만 못 읽는 경우가 있다.
                    # 변화는 포기하되 현재 구성까지 잃을 이유는 없다.
                    break
                raise DataUnavailable(f"13F information table unreadable for CIK {cik}")
            scale, holdings, options = _normalise_scale(holdings, options)
            built.append(ManagerPortfolio(
                cik=cik,
                name=str(payload.get("name") or ""),
                form=form,
                filed=_date(filed),
                period=_date(period),
                accession=accession,
                holdings=holdings,
                row_count=rows,
                value_scale=scale,
                options_value_usd=options,
            ))
        return tuple(built)

    def _fetch_13f_table(
        self, cik: str, accession: str
    ) -> tuple[tuple[ManagerHolding, ...], int, float]:
        """정보표 XML을 찾아 행을 읽는다.

        제출물 안에 XML이 여러 개다(표지 `primary_doc.xml` + 정보표). 이름
        규칙이 제출자마다 달라 이름으로 고르지 않고 **`infoTable`이 든 파일**을
        찾는다.
        """
        base = f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession}/"
        listing = self._request_json(f"{base}index.json")
        items = ((listing or {}).get("directory") or {}).get("item") or []
        names = [
            str(item.get("name"))
            for item in items
            if str(item.get("name", "")).lower().endswith(".xml")
        ]
        # 표지를 먼저 열어 낭비할 이유가 없다.
        names.sort(key=lambda name: "primary_doc" in name.lower())

        for name in names:
            body = self._request(f"{base}{name}", accept="application/xml")
            try:
                root = ElementTree.fromstring(body)
            except ElementTree.ParseError:
                continue
            blocks = [node for node in root.iter() if _local(node.tag) == "infoTable"]
            if not blocks:
                continue
            return _parse_info_table(blocks)
        return (), 0, 0.0
