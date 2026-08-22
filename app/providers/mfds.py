"""식품의약품안전처 의약품 제품 허가정보 (공공데이터포털 data.go.kr) — daily permits by permit date.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.26): dataset 15095677 on the
public data portal — 비용 무료, 이용허락범위 "이용허락범위 제한 없음" (the portal's
widest grade, the same as the FSC datasets in §3.9), 개발계정 자동승인.  The
operator applied for and received access on 2026-08-22; the portal issues one
service key per account, so ``MFDS_API_KEY`` may simply be the FSC key.  Source
attribution is shown with the values.

Only ``getDrugPrdtPrmsnDtlInq06`` is used — it is the endpoint that accepts an
``item_permit_date`` (YYYYMMDD) filter (verified 2026-08-22: 2026-06-30 → 62
items, 2026-08-21 → 9).  The list endpoint ignores date filters and is not
ordered by date, so the lane asks for each day of a trailing window instead.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, unquote, urlencode

from .base import DataUnavailable, RateLimited

PROVIDER_ID = "mfds_drug_permit"
PUBLISHER = "식품의약품안전처 (공공데이터포털)"
ATTRIBUTION = "출처: 식품의약품안전처 의약품 제품 허가정보 (공공데이터포털)"
ATTRIBUTION_EN = "Source: Ministry of Food and Drug Safety — drug product permit data (data.go.kr)"
API_BASE = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"
DETAIL_ENDPOINT = "getDrugPrdtPrmsnDtlInq06"
DATASET_URL = "https://www.data.go.kr/data/15095677/openapi.do"
PORTAL_URL = "https://www.data.go.kr/"
ITEM_URL = "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetailCache?cacheSeq={item_seq}"
LICENSE_QUOTE = (
    "공공데이터포털 데이터셋 15095677: 비용부과유무 무료 · 이용허락범위 \"이용허락범위 제한 없음\" · "
    "심의유형 개발단계 자동승인 (접근 2026-08-22; 운영자 활용신청 승인 2026-08-22)"
)
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_ROWS = 100
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"
# data.go.kr gateway reason codes (OpenAPI_ServiceResponse.cmmMsgHeader.returnReasonCode)
_RATE_LIMIT_CODES = {"22"}
_KEY_CODES = {"30", "31", "32", "33"}
_CODE_RE = re.compile(r"\[[A-Z]\d+\]")

Transport = Callable[[str, dict[str, str], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def normalized_key(raw: str) -> str:
    """Accept either the portal's 'Encoding' key (already percent-encoded) or the 'Decoding' key."""
    return quote(unquote(raw.strip()), safe="")


def _iso_date(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return None


def split_ingredients(value: Any) -> list[str]:
    """``[M262653]에독사반토실산염수화물|[M081161]크로스포비돈`` → names without the bracketed codes."""
    if not isinstance(value, str) or not value.strip():
        return []
    names: list[str] = []
    for part in value.split("|"):
        name = _CODE_RE.sub("", part).strip()
        if name and name not in names:
            names.append(name)
    return names


def parse_permit(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    item_seq = str(raw.get("ITEM_SEQ") or "").strip()
    if not item_seq:
        return None
    newdrug = (raw.get("NEWDRUG_CLASS_NAME") or "").strip() or None
    return {
        "item_seq": item_seq,
        "item_name": (raw.get("ITEM_NAME") or "").strip() or None,
        "item_eng_name": (raw.get("ITEM_ENG_NAME") or "").strip() or None,
        "entp_name": (raw.get("ENTP_NAME") or "").strip() or None,
        "entp_eng_name": (raw.get("ENTP_ENG_NAME") or "").strip() or None,
        "permit_date": _iso_date(raw.get("ITEM_PERMIT_DATE")),
        "permit_kind": (raw.get("PERMIT_KIND_NAME") or "").strip() or None,
        "etc_otc": (raw.get("ETC_OTC_CODE") or "").strip() or None,
        "newdrug_class": newdrug,
        "rare": str(raw.get("RARE_DRUG_YN") or "").upper() == "Y",
        "main_ingredients": split_ingredients(raw.get("MAIN_ITEM_INGR"))[:6],
        "atc_code": (raw.get("ATC_CODE") or "").strip() or None,
        "material_flag": (raw.get("MAKE_MATERIAL_FLAG") or "").strip() or None,
        "industry": (raw.get("INDUTY_TYPE") or "").strip() or None,
        "cancel_name": (raw.get("CANCEL_NAME") or "").strip() or None,
        "cancel_date": _iso_date(raw.get("CANCEL_DATE")),
        "change_date": _iso_date(raw.get("CHANGE_DATE")),
        "reexam_target": (raw.get("REEXAM_TARGET") or "").strip() or None,
        "url": ITEM_URL.format(item_seq=item_seq),
    }


def parse_response(status: int, body: str) -> dict[str, Any]:
    """Map the portal's two error shapes and the service's header/body to rows or exceptions."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DataUnavailable(f"MFDS API returned an unreadable response (HTTP {status})") from exc
    if not isinstance(data, dict):
        raise DataUnavailable("MFDS API returned a non-object payload")
    gateway = data.get("OpenAPI_ServiceResponse")
    if isinstance(gateway, dict):
        head = gateway.get("cmmMsgHeader") if isinstance(gateway.get("cmmMsgHeader"), dict) else {}
        code = str(head.get("returnReasonCode") or "")
        message = head.get("errMsg") or head.get("returnAuthMsg") or "gateway error"
        if code in _RATE_LIMIT_CODES:
            raise RateLimited(f"data.go.kr gateway: {message} ({code})")
        raise DataUnavailable(f"data.go.kr gateway: {message} ({code})")
    header = data.get("header") if isinstance(data.get("header"), dict) else {}
    result_code = str(header.get("resultCode") or "")
    if result_code not in ("00", "0"):
        if result_code in _RATE_LIMIT_CODES:
            raise RateLimited(f"MFDS API {result_code}: {header.get('resultMsg')}")
        raise DataUnavailable(f"MFDS API {result_code}: {header.get('resultMsg')}")
    body_obj = data.get("body") if isinstance(data.get("body"), dict) else {}
    total = body_obj.get("totalCount")
    rows = [row for row in (parse_permit(item) for item in body_obj.get("items") or []) if row]
    return {
        "total_count": int(total) if isinstance(total, int) else None,
        "page_no": body_obj.get("pageNo"),
        "num_of_rows": body_obj.get("numOfRows"),
        "permits": rows,
    }


class MfdsProvider:
    """Keyed GETs against the detail endpoint, one day per call; the key never leaves the ingest process."""

    name = PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        rows: int = DEFAULT_ROWS,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("MFDS (data.go.kr) service key is required")
        self._api_key = normalized_key(api_key)
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self.rows = max(1, min(100, int(rows)))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_permits_on(self, day: dt.date, *, page: int = 1) -> dict[str, Any]:
        params = {"type": "json", "numOfRows": str(self.rows), "pageNo": str(max(1, int(page))), "item_permit_date": day.strftime("%Y%m%d")}
        # serviceKey is appended raw: it is already percent-encoded and urlencode would encode it again.
        url = f"{API_BASE}/{DETAIL_ENDPOINT}?serviceKey={self._api_key}&{urlencode(params)}"
        parsed = self._request(url)
        parsed["day"] = day.isoformat()
        parsed["fetched_at"] = _utc_iso(self._wall_clock())
        return parsed

    def _request(self, url: str) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                status, body = self._transport(url, headers, self.timeout)
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            else:
                if 500 <= int(status) < 600:
                    last_error = DataUnavailable(f"MFDS API HTTP {status}")
                else:
                    return parse_response(int(status), body)
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("MFDS API is unavailable") from last_error
