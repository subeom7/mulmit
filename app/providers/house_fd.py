"""미 하원 서기국(Clerk) 재정공시 — STOCK Act 주기거래보고(PTR).

법정 공시다. STOCK Act(2012)는 의원의 증권 거래를 45일 내 보고하게 하고, 하원
서기국은 그 보고서를 공개한다. 연간 인덱스는 구조화 XML(zip)로, 개별 PTR은
PDF로 제공된다: 전자 제출분은 텍스트 PDF라 거래 표를 추출할 수 있고, 수기
제출분은 스캔 이미지라 추출할 수 없다 — 그런 건은 목록과 원문 링크만 싣는다.

**사용 제한이 명문으로 있다.** Ethics in Government Act §105(c)(5 U.S.C. app.):
보고서를 ① 불법 목적, ② 상업 목적(단, **news and communications media의 일반
공중 배포는 제외**), ③ 개인 신용평가, ④ 정치·자선 자금모집에 쓰는 것은
불법이며 건당 최대 $10,000의 민사 제재가 가능하다. Mulmit의 표시는 무료 공개
사이트에서 출처·원문 링크와 함께 일반 공중에 전달하는 것으로 그 제외 사유에
해당한다고 판단하고(등록부 §3.14), 같은 제한을 응답에 그대로 실어 이용자에게도
고지한다.

파싱 원칙: 추출된 텍스트가 엄격한 패턴과 일치하는 거래만 싣는다. 일치하지
않는 행은 버리고 그 사실을 상태로 남긴다 — 이름이 걸린 데이터에서 추측은
곧 오보다.

상원(eFD)은 서버 수집이 봇 차단(403)으로 막혀 있어 이 lane에 없다. 차단을
우회하지 않는다는 원칙에 따라 보류 상태로 등록부에 기록돼 있다.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import time
import zipfile
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from pypdf import PdfReader

from .base import DataUnavailable, RateLimited

HOUSE_FD_PROVIDER_ID = "house_fd"
HOUSE_FD_PUBLISHER = "Clerk of the U.S. House of Representatives"
HOUSE_FD_PUBLISHER_URL = "https://disclosures-clerk.house.gov/"
HOUSE_FD_BASE = "https://disclosures-clerk.house.gov/public_disc"
HOUSE_FD_INDEX_URL = HOUSE_FD_BASE + "/financial-pdfs/{year}FD.zip"
HOUSE_FD_PDF_URL = HOUSE_FD_BASE + "/ptr-pdfs/{year}/{doc_id}.pdf"
HOUSE_FD_SEARCH_URL = "https://disclosures-clerk.house.gov/FinancialDisclosure"
HOUSE_FD_ATTRIBUTION = "Source: Clerk of the U.S. House of Representatives, Financial Disclosure Reports."

# EIGA §105(c) — 원문 요지를 그대로 전달한다. 화면과 API 응답에 실린다.
EIGA_105C_NOTICE_EN = (
    "5 U.S.C. app. §105(c): it is unlawful to obtain or use these reports for any "
    "unlawful purpose; for any commercial purpose other than by news and "
    "communications media for dissemination to the general public; for determining "
    "or establishing any individual's credit rating; or for the solicitation of "
    "money for any political, charitable, or other purpose."
)
EIGA_105C_NOTICE_KO = (
    "미 윤리법 §105(c)에 따라 이 보고서를 불법 목적, 일반 공중 배포 외의 상업 목적, "
    "개인 신용평가, 정치·자선 자금모집에 사용하는 것은 금지됩니다."
)

# 전자 제출 PTR 텍스트의 거래 서명: 유형 + 거래일 + 신고일 + 금액 구간.
# 서버측 추출은 자산명과 서명을 한 줄에 합치기도 하므로 줄 중간에서도 찾는다.
# 단, 유형 문자 앞이 글자면("CommonP …") 그 서명은 자산에 붙은 것으로 보고
# 버린다 — 붙은 레이아웃을 쪼개려는 추측은 오보를 만든다.
_SIG = re.compile(
    r"(?<![A-Za-z])(?P<type>P|S \(partial\)|S|E)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s*"
    r"(?P<notification>\d{2}/\d{2}/\d{4})\s*"
    # "-" 뒤 상한이 다음 줄로 넘어간 경우("$15,001 -")도 대시까지 잡아 두어야
    # 하한만 남은 값이 정확한 금액처럼 보이지 않는다. 상한은 tail 병합이 잇는다.
    r"(?P<amount>\$[\d,]+(?:\s*-\s*(?:\$[\d,]+)?)?)"
)
_AMOUNT_TAIL = re.compile(r"^\$[\d,]+\s*$")
_OWNER_PREFIX = re.compile(r"^(?:\d{8,12})?\s*(?P<owner>SP|JT|DC)\s+")
_TICKER = re.compile(r"\((?P<ticker>[A-Z][A-Z0-9.\-]{0,9})\)\s*\[?")
_ASSET_CODE = re.compile(r"\[(?P<code>[A-Z]{2,3})\]")
# 낱글자·두 글자 대문자 토큰만으로 된 줄은 뭉개진 구역 제목이다 ("P T R", "F I").
_MANGLED_HEADING = re.compile(r"^[A-Z]{1,2}(?:\s+[A-Z]{1,2})*$")
# 자산 앞에 섞여 들어온 제목 잔여물: 짧은 대문자 토큰이 3개 이상 이어지는 머리.
_MANGLED_LEAD = re.compile(r"^(?:[A-Z]{1,2}\s+){3,}")
_FILING_ID = re.compile(r"Filing ID #\d+\s*")
# 검증 게이트: 자산명에 날짜나 금액이 남아 있으면 레이아웃이 섞인 것이다.
_ASSET_POLLUTION = re.compile(r"\d{2}/\d{2}/\d{4}|\$[\d,]")
_NOISE_PREFIXES = (
    "Clerk of the House", "* For the complete list", "ID Owner Asset",
    "Type", "Date Notification", "Date", "Amount Cap.", "Gains >", "$200?",
    "Digitally Signed",
)
# "Filing ID #…"는 줄 전체가 아니라 토큰만 걷어낸다 — 같은 줄에 다음 거래의
# 자산이 이어지는 추출이 실제로 있다(_clean_asset의 _FILING_ID 스크럽).

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _iso(us_date: str) -> str | None:
    """M/D/YYYY 또는 MM/DD/YYYY → ISO. 형식이 다르면 None — 추측하지 않는다."""
    parts = us_date.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        month, day, year = (int(p) for p in parts)
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if any(stripped.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return True
    return bool(_MANGLED_HEADING.match(stripped))


def _clean_asset(asset_text: str) -> tuple[str | None, str]:
    """자산 버퍼에서 (소유자, 자산명)을 뽑고 알려진 잔여물을 걷어낸다."""
    asset_text = _FILING_ID.sub("", asset_text)
    asset_text = _MANGLED_LEAD.sub("", asset_text).strip()
    owner = None
    owner_match = _OWNER_PREFIX.match(asset_text)
    if owner_match:
        owner = owner_match.group("owner")
        asset_text = asset_text[owner_match.end():].strip()
    return owner, re.sub(r"\s+", " ", asset_text)


def parse_ptr_text(text: str) -> tuple[list[dict[str, Any]], int]:
    """전자 PTR 텍스트에서 (거래 목록, 서명 수)를 뽑는다.

    서명(유형+두 날짜+금액)을 줄 안 어디서든 찾고, 자산명은 직전 서명 이후
    누적된 텍스트에서 온다. 자산명이 비었거나 날짜·금액이 섞여 있으면 그
    거래는 싣지 않는다 — 개수 차이는 호출자가 상태로 보고한다.
    """
    # pypdf 버전에 따라 추출 텍스트에 NUL 등 제어문자가 끼어든다(운영 실측:
    # "P\x00\x00 T\x00…"). \s에 잡히지 않아 모든 스크럽을 비껴가므로 먼저 지운다.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)

    transactions: list[dict[str, Any]] = []
    signatures = 0
    asset_parts: list[str] = []
    tail_open = False  # 직전 서명의 금액이 "$X -"로 끝나 하한만 있는 상태

    for raw in text.splitlines():
        line = raw.strip()
        if tail_open:
            tail_open = False
            # 금액 구간이 줄바꿈으로 쪼개진 경우("$15,001 -" ↵ "$50,000")를 잇는다.
            if transactions and _AMOUNT_TAIL.match(line):
                transactions[-1]["amount"] = f"{transactions[-1]['amount']} {line}".strip()
                continue
        if _is_noise(line):
            continue
        matches = list(_SIG.finditer(line))
        if not matches:
            if ":" in line:  # 메타데이터 줄 (Name:, F S : New, S O : …)
                continue
            if line:
                asset_parts.append(line)
            continue

        cursor = 0
        last_appended = False
        for match in matches:
            signatures += 1
            prefix = line[cursor:match.start()].strip()
            if prefix and ":" not in prefix:
                asset_parts.append(prefix)
            cursor = match.end()
            owner, asset_text = _clean_asset(" ".join(asset_parts).strip())
            asset_parts = []
            asset_name = _ASSET_CODE.sub("", asset_text).strip()
            if not asset_name or _ASSET_POLLUTION.search(asset_name):
                last_appended = False
                continue  # 비었거나 레이아웃이 섞인 자산은 싣지 않는다
            ticker_match = _TICKER.search(asset_text)
            code_match = _ASSET_CODE.search(asset_text)
            amount = re.sub(r"\s+", " ", match.group("amount")).strip()
            transactions.append({
                "owner": owner,
                "asset": asset_name,
                "ticker": ticker_match.group("ticker") if ticker_match else None,
                "asset_code": code_match.group("code") if code_match else None,
                "type": match.group("type"),
                "date": _iso(match.group("date")),
                "notification_date": _iso(match.group("notification")),
                "amount": amount,
            })
            last_appended = True
        remainder = line[cursor:].strip()
        if not remainder and last_appended and transactions[-1]["amount"].endswith("-"):
            tail_open = True
        elif remainder and ":" not in remainder:
            asset_parts.append(remainder)

    return transactions, signatures


class HouseFdProvider:
    """연간 인덱스 zip과 개별 PTR PDF만 아는 작은 클라이언트."""

    name = HOUSE_FD_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 1.0,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.request_interval = max(0.0, float(request_interval))
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

    def _get(self, url: str) -> bytes:
        request = Request(
            url,
            headers={"User-Agent": "Mulmit/1.0 (subeomkwon@gmail.com)", "Accept": "*/*"},
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
                    raise RateLimited("House Clerk throttled the request") from exc
                raise DataUnavailable(f"House Clerk HTTP error {exc.code} for {url}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"House Clerk unreachable for {url}") from exc
        raise AssertionError("unreachable")

    def fetch_ptr_index(self, year: int) -> list[dict[str, Any]]:
        """한 해의 PTR 신고 인덱스. 구조화 XML이므로 파싱 위험이 없다."""
        raw = self._get(HOUSE_FD_INDEX_URL.format(year=year))
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                inner = next(n for n in archive.namelist() if n.endswith(".xml"))
                data = archive.read(inner).decode("utf-8-sig", "replace")
            root = ElementTree.fromstring(data)
        except (zipfile.BadZipFile, StopIteration, ElementTree.ParseError) as exc:
            raise DataUnavailable(f"House FD index for {year} is unreadable") from exc

        rows = []
        for member in root:
            if (member.findtext("FilingType") or "").strip() != "P":
                continue
            doc_id = (member.findtext("DocID") or "").strip()
            filed = _iso(member.findtext("FilingDate") or "")
            if not doc_id or not filed:
                continue
            name = " ".join(part for part in (
                (member.findtext("Prefix") or "").strip(),
                (member.findtext("First") or "").strip(),
                (member.findtext("Last") or "").strip(),
                (member.findtext("Suffix") or "").strip(),
            ) if part)
            rows.append({
                "doc_id": doc_id,
                "name": name,
                "state_district": (member.findtext("StateDst") or "").strip(),
                "filed_date": filed,
                "year": year,
                "pdf_url": HOUSE_FD_PDF_URL.format(year=year, doc_id=doc_id),
            })
        return rows

    def fetch_ptr_transactions(
        self, doc_id: str, year: int
    ) -> tuple[list[dict[str, Any]], int] | None:
        """한 PTR의 거래 목록. 스캔 제출분(텍스트 없음)은 None."""
        raw = self._get(HOUSE_FD_PDF_URL.format(year=year, doc_id=doc_id))
        try:
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # pypdf는 깨진 PDF에서 다양한 예외를 던진다
            raise DataUnavailable(f"House PTR {doc_id} PDF is unreadable") from exc
        if len(text.strip()) < 50:
            return None
        return parse_ptr_text(text)
