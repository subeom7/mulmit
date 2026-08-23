"""종목 검색 관심도 — 네이버 데이터랩 검색어 트렌드를 종목에 붙인다.

국내 개인 비중이 높은 종목에서 **관심의 급등**은 값이 있는 축이다. 다만 상류가
주는 것이 무엇인지 정확히 알고 써야 한다.

**정규화가 요청 단위다.** 데이터랩은 "요청된 기간 중 검색 횟수가 가장 높은 시점을
100으로" 두고 나머지를 상대값으로 준다. 절댓값은 주지 않는다(공식 문서: "절댓값
제공은 아직 고려하고 있지 않습니다"). 그래서 종목 A를 혼자 조회한 100과 종목 B를
혼자 조회한 100은 **같은 크기가 아니다**. 종목이 다섯을 넘으면 요청이 갈라지고,
갈라진 요청 사이의 100은 서로 다른 것을 뜻한다.

여기서 택한 길: **요청 사이의 값을 섞지 않는다.** 각 종목을 자기 자신의 창에
대해서만 읽는다 — "이 종목의 오늘 관심도가 지난 N일 중 어디쯤인가"(백분위)와
"평소(중앙값) 대비 몇 배인가"(배수). 둘 다 **한 계열 안에서 끝나는 계산**이라
요청이 갈라져도 뜻이 변하지 않고, 그래서 종목 간에 나란히 놓아도 된다. 반면
`ratio` 원값은 같은 요청 안에서만 비교할 수 있어서 `batch` 번호를 함께 실어
보낸다 — 화면이 실수로 섞으면 그 번호로 걸러야 한다.

**이 lane은 저장하지 않는다.** 요청마다 창 전체가 오므로 이력 blob이 필요 없고,
없으면 약관의 "허용 범위 초과" 판단을 아예 마주치지 않는다(등록부 §6.7).
남는 것은 상류를 두 번 때리지 않기 위한 메모리 TTL 캐시 하나뿐이다.

**만들 수 없는 것**: "오늘 가장 많이 검색된 종목" 같은 실시간 랭킹. 랭킹
엔드포인트가 없고 절댓값이 없어 우리가 합성할 수도 없다. 급등 정도로 줄을 세울
수는 있어도 그것은 검색량 순위가 아니다 — 화면 문구가 이 둘을 흐리면 안 된다.

게이트: ``NAVER_DATALAB_ENABLED`` + 클라이언트 아이디/시크릿 (등록부 §6.7).
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics
from typing import Any

from . import config, data_rights, store
from .providers.base import DataUnavailable, RateLimited
from .providers.naver_datalab import (
    DATALAB_ATTRIBUTION,
    DATALAB_ATTRIBUTION_EN,
    DATALAB_DOCS_URL,
    DATALAB_PROVIDER_ID,
    DATALAB_PUBLISHER,
    DATALAB_PUBLISHER_EN,
    DATALAB_PUBLISHER_URL,
    DATALAB_TERMS_URL,
    MAX_GROUPS,
    DatalabConfigError,
    DatalabProvider,
)

log = logging.getLogger(__name__)

WINDOW_DAYS = 90
# 데이터랩은 어제까지를 준다. 오늘을 끝으로 달라고 하면 마지막 점이 비거나 덜 찬다.
LAG_DAYS = 1
# "평소"는 **같은 요일**의 중앙값이다. 주식 검색은 주중/주말 진폭이 압도적이라
# (2026-08-24 실측: 삼성전자 평일 중앙값 55~64 대 토 8.9·일 7.5 — 주말이 평일의
# 12~14%, 현대차도 20~23%), 요일을 섞은 기준선에 오늘을 견주면 토·일마다 "85%
# 급락", 월요일마다 "7배 급등"이 찍힌다. 에러 없이 매주 거짓말을 하는 종류다.
# 같은 요일끼리 견주면 그 주기가 분자와 분모에서 함께 사라진다.
#
# 표본이 이보다 적으면 중앙값이 흔들려서 배수가 뜻을 잃는다 — 그때는 숫자를
# 내지 않는다. 90일 창이면 요일당 12~13개가 모인다.
MIN_WEEKDAY_SAMPLES = 4
_KST = dt.timezone(dt.timedelta(hours=9))

_DEFAULT_PROVIDER: DatalabProvider | None = None


class KrSearchInterestDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _provider() -> DatalabProvider:
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        _DEFAULT_PROVIDER = DatalabProvider(
            client_id=config.NAVER_DATALAB_CLIENT_ID,
            client_secret=config.NAVER_DATALAB_CLIENT_SECRET,
            timeout=config.NAVER_DATALAB_TIMEOUT,
            retries=config.NAVER_DATALAB_RETRIES,
            ttl=float(config.NAVER_DATALAB_MAX_AGE),
        )
    return _DEFAULT_PROVIDER


def reset_provider() -> None:
    """테스트가 주입한 것을 되돌린다."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = None


def _require_lane() -> None:
    if not data_rights.kr_search_interest_enabled():
        raise KrSearchInterestDisabled("disabled")


def seoul_today(now: dt.datetime | None = None) -> dt.date:
    moment = now or dt.datetime.now(dt.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(_KST).date()


def watchlist() -> list[str]:
    """관심도를 볼 종목 코드. 운영자가 env로 정하고, 없으면 비어 있다.

    로스터 전체(3,000여 종목)를 도는 설계는 쿼터가 아니라 **뜻**에서 틀린다 —
    거래가 거의 없는 종목의 검색 추이는 잡음이고, 그것을 급등이라 부르면 화면이
    거짓말을 한다.
    """
    raw = config.NAVER_DATALAB_WATCHLIST
    return [code.strip().upper() for code in raw.split(",") if code.strip()]


def _label_for(code: str) -> dict[str, str] | None:
    """검색어는 회사 이름이다. 로스터에 없는 코드는 만들어 내지 않고 버린다."""
    listing = store.get_kr_listing(code)
    if not listing:
        return None
    name = str(listing.get("itms_nm") or "").strip()
    if not name:
        return None
    return {"code": code, "name": name, "market": str(listing.get("mrkt_ctg") or "").strip()}


def _describe(series: list[dict[str, Any]]) -> dict[str, Any]:
    """한 계열 안에서 끝나는 계산만 한다 — 요청이 갈라져도 뜻이 변하지 않도록.

    그리고 **같은 요일끼리만** 견준다. 위 MIN_WEEKDAY_SAMPLES 주석의 실측대로
    주간 주기가 값의 대부분을 설명하기 때문에, 요일을 섞으면 주말마다 급락이,
    월요일마다 급등이 나온다.
    """
    values = [float(point["ratio"]) for point in series]
    latest = values[-1]
    peak = max(values)

    latest_day = _weekday_of(series[-1]["period"])
    same_weekday = [
        float(point["ratio"])
        for point in series[:-1]
        if _weekday_of(point["period"]) == latest_day
    ]

    baseline: float | None = None
    multiple: float | None = None
    percentile: float | None = None
    if len(same_weekday) >= MIN_WEEKDAY_SAMPLES:
        baseline = statistics.median(same_weekday)
        # 기준선이 0이면(그 요일 내내 검색이 거의 없었다면) 배수는 뜻이 없다.
        multiple = round(latest / baseline, 2) if baseline > 0 else None
        below = sum(1 for value in same_weekday if value < latest)
        percentile = round(below / len(same_weekday) * 100.0, 1)

    return {
        "latest": round(latest, 2),
        "peak": round(peak, 2),
        "baseline": None if baseline is None else round(baseline, 2),
        "percentile": percentile,
        "vs_baseline": multiple,
        "points": len(values),
        # 무엇에 견줬는지 밝힌다 — 같은 요일 몇 개인지 모르면 배수를 읽을 수 없다.
        "compared_to": {"weekday": latest_day, "samples": len(same_weekday)},
        "at_window_high": latest >= peak,
    }


def _weekday_of(period: str) -> int:
    return dt.date.fromisoformat(period).weekday()

def _batches(entries: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    return [entries[i : i + MAX_GROUPS] for i in range(0, len(entries), MAX_GROUPS)]


def build(
    codes: list[str] | None = None,
    *,
    today: dt.date | None = None,
    provider: DatalabProvider | None = None,
) -> dict[str, Any]:
    """워치리스트의 검색 관심도. 한 요청당 최대 5종목, 요청 사이 값은 섞지 않는다."""
    _require_lane()
    wanted = [code.strip().upper() for code in (codes or watchlist()) if code.strip()]
    if not wanted:
        raise DataUnavailable("검색 관심도를 볼 종목이 지정되지 않았다")

    entries = [entry for entry in (_label_for(code) for code in wanted) if entry]
    if not entries:
        raise DataUnavailable("워치리스트의 종목이 국내 로스터에 없다")

    end = (today or seoul_today()) - dt.timedelta(days=LAG_DAYS)
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)
    client = provider or _provider()

    stocks: list[dict[str, Any]] = []
    for index, batch in enumerate(_batches(entries)):
        groups = [(entry["name"], [entry["name"]]) for entry in batch]
        try:
            payload = client.fetch_trend(groups, start=start, end=end, time_unit="date")
        except (DataUnavailable, RateLimited):
            # 한 묶음이 실패해도 나머지는 살린다. 빈 자리를 지어내지는 않는다.
            log.warning("datalab batch %s failed", index, exc_info=True)
            continue
        by_title = {group["title"]: group for group in payload.get("groups") or []}
        for entry in batch:
            group = by_title.get(entry["name"])
            if not group or not group.get("series"):
                continue
            stocks.append(
                {
                    **entry,
                    "hub": f"/stock/{entry['code']}",
                    # 같은 batch 안에서만 ratio 원값을 비교할 수 있다.
                    "batch": index,
                    "series": group["series"],
                    **_describe(group["series"]),
                }
            )

    if not stocks:
        raise DataUnavailable("데이터랩이 워치리스트에서 읽을 수 있는 계열을 주지 않았다")

    # 줄 세우기는 자기 대비 급등 정도로만 한다 — 검색량 순위가 아니다.
    # 배수를 못 낸 종목(같은 요일 표본 부족)은 뒤로 — 0으로 세우면 급락처럼 보인다.
    stocks.sort(key=lambda row: (row.get("vs_baseline") is not None, row.get("vs_baseline") or 0.0, row.get("percentile") or 0.0), reverse=True)

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": WINDOW_DAYS},
        "stocks": stocks,
        "count": len(stocks),
        "basis_ko": (
            f"네이버 통합검색 {WINDOW_DAYS}일 검색 추이입니다. 값은 절댓값이 아니라 "
            "요청 기간의 최댓값을 100으로 둔 상대값입니다. 주식 검색은 주말에 평일의 10~20%로 "
            "떨어지므로 **같은 요일끼리** 견줍니다. 종목 간 비교는 자기 평소 대비 "
            "배수와 백분위로만 합니다. 검색량 순위가 아닙니다."
        ),
        "basis_en": (
            f"NAVER integrated-search interest over {WINDOW_DAYS} days. Values are relative to "
            "each request's own peak (100), not absolute counts. Stock search drops to 10-20% of "
            "weekday levels at weekends, so each day is compared with the same weekday. Stocks "
            "are ranked only by "
            "how far each sits above its own baseline. This is not a search-volume ranking."
        ),
        "attribution": {
            "text": DATALAB_ATTRIBUTION_EN,
            "text_ko": DATALAB_ATTRIBUTION,
            "url": DATALAB_PUBLISHER_URL,
            "docs": DATALAB_DOCS_URL,
        },
        "source": {
            "provider": DATALAB_PROVIDER_ID,
            "publisher": DATALAB_PUBLISHER,
            "publisher_en": DATALAB_PUBLISHER_EN,
            "terms_url": DATALAB_TERMS_URL,
        },
        "rights": {"status": "granted", "stored": False},
    }


__all__ = [
    "DatalabConfigError",
    "KrSearchInterestDisabled",
    "build",
    "reset_provider",
    "watchlist",
]
