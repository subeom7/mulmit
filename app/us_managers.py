"""13F 기관 포트폴리오 — 널리 알려진 운용자 여섯의 미국 상장주식 구성.

국민연금 파이(`kr_pension_portfolio`)의 미국 쪽이다. 다만 원천의 성질이 달라
같은 화면을 그대로 옮길 수 없다. **13F로 만들 수 없는 것을 먼저 적는다:**

    공매도 · 채권 · 현금 · 해외 상장 주식 · 사모 지분 · 옵션의 실제 익스포저

그래서 이 파이는 "그 사람의 자산 전부"가 아니라 **미국 상장주식 롱 포지션의
구성**이다. 이 구분이 흐려지면 화면이 거짓말을 한다 — 브리지워터의 13F는
$24B인데 회사가 실제로 굴리는 돈은 그보다 훨씬 크고, 대부분은 이 서식에 오지
않는 매크로·선물이다.

시점도 다르다. 분기 말 기준에 **45일 안에** 내면 되므로 화면의 사진은 최대 한
분기 반쯤 지난 것이다. 늦게 낸 제출자는 더 밀린다 — 실측(2026-08-24) 퍼싱
스퀘어의 최신 신고는 2026 Q1이고, 다른 다섯은 Q2다.

숫자를 다루며 조심한 곳
-----------------------
**단위가 제출자마다 다르다.** 2023년 개정으로 `value`는 달러가 됐지만 여전히
천 달러로 내는 곳이 있다. 판별은 서식의 기준선에서 가져왔다(`_normalise_scale`).
섞어서 한 화면에 올리면 조용히 천 배 틀린 그림이 나온다.

**한 종목이 여러 행으로 온다.** 버크셔의 최근 제출은 89행이지만 발행사는
26곳이다. 합치지 않으면 애플이 파이에 여러 조각으로 나타난다.

**조각 수는 신고자마다 다르게 정한다.** 국민연금과 같은 규칙 — 이름 붙은
조각이 과반이 되어야 그림이 보유 종목을 말한다. 실측한 최소 N은 버크셔 3 ·
퍼싱 3 · 두케인 9 · ARK 15 · 피셔 19 · **브리지워터 21**이다. 20으로 못 박으면
브리지워터만 49.8%로 규칙을 깬다.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from . import config, data_rights, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.sec_edgar import (
    SEC_PUBLISHER,
    SEC_PUBLISHER_URL,
    SEC_RIGHTS_NOTICE,
    SEC_RIGHTS_NOTICE_KO,
    EdgarNotFound,
    ManagerPortfolio,
    SecEdgarProvider,
)

log = logging.getLogger(__name__)

CACHE_KEY = "sec_13f_managers_v1"

#: 파이에 이름을 붙일 조각의 기본 개수. 과반에 못 미치면 아래에서 늘린다.
BASE_SLICES = 20

#: 조각을 늘릴 수 있는 한계. 여기서도 과반이 안 되면 그 사실을 화면이 말한다.
MAX_SLICES = 30

#: 표로 보여줄 행 수.
TABLE_ROWS = 25

#: 지수 상품으로 보이는 발행사 이름. **휴리스틱이라 단정하지 않는다** —
#: 화면에서도 "지수 상품으로 보이는 항목"이라고만 말한다. 브리지워터의 상위
#: 두 자리가 여기 걸리는데(SPDR·iShares 합 26.5%), 그 사실을 숨기면 "달리오의
#: 최대 보유는 S&P 500"이라는 그림이 설명 없이 나간다.
_INDEX_HINTS = ("SPDR", "ISHARES", "VANGUARD", "INVESCO QQQ", "SELECT SECTOR",
                "POWERSHARES", "PROSHARES", "SCHWAB STRATEGIC", "INDEX TR")


@dataclass(frozen=True)
class Manager:
    slug: str
    cik: str
    fund_ko: str
    fund_en: str
    person_ko: str
    person_en: str
    #: 인물과 신고자를 나란히 놓는 것이 오해가 되는 경우에만 채운다.
    person_note_ko: str | None = None
    person_note_en: str | None = None


MANAGERS: tuple[Manager, ...] = (
    Manager("berkshire", "0001067983", "버크셔 해서웨이", "Berkshire Hathaway",
            "워런 버핏", "Warren Buffett"),
    Manager("duquesne", "0001536411", "두케인 패밀리 오피스", "Duquesne Family Office",
            "스탠리 드러켄밀러", "Stanley Druckenmiller"),
    Manager("pershing", "0001336528", "퍼싱 스퀘어", "Pershing Square",
            "빌 애크먼", "Bill Ackman"),
    Manager("ark", "0001697748", "ARK 인베스트", "ARK Invest",
            "캐시 우드", "Cathie Wood"),
    Manager("fisher", "0000850529", "피셔 애셋 매니지먼트", "Fisher Asset Management",
            "켄 피셔", "Ken Fisher"),
    Manager("bridgewater", "0001350694", "브리지워터", "Bridgewater Associates",
            "레이 달리오", "Ray Dalio",
            person_note_ko=(
                "레이 달리오는 2022년 9월 지배권을 이사회에 넘기고 공동 CIO에서 "
                "물러났습니다. 이 신고는 회사의 것이며 그의 개인 포트폴리오가 아닙니다."
            ),
            person_note_en=(
                "Ray Dalio handed his voting control to the board and stepped down as "
                "co-CIO in September 2022. This filing is the firm's, not his own book."
            )),
)


class ManagersDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.SEC_EDGAR_ENABLED:
        raise ManagersDisabled("disabled")
    if not config.SEC_EDGAR_USER_AGENT:
        raise ManagersDisabled("not_configured")


def _looks_like_index_product(issuer: str) -> bool:
    return any(hint in issuer for hint in _INDEX_HINTS)


def _slice_count(holdings: list[dict[str, Any]], total: float) -> tuple[int, bool]:
    """이름 붙은 조각이 과반이 되는 지점까지 늘린다.

    돌려주는 두 번째 값은 **한계까지 늘려도 과반이 안 됐는가**다. 그런 신고자는
    파이가 보유 종목이 아니라 나머지를 말하게 되므로 화면이 그 사실을 밝힌다.
    """
    if total <= 0:
        return 0, False
    running = 0.0
    for index, row in enumerate(holdings[:MAX_SLICES], start=1):
        running += row["value"]
        if index >= BASE_SLICES and running / total > 0.5:
            return index, False
    capped = min(len(holdings), MAX_SLICES)
    reached = sum(row["value"] for row in holdings[:capped])
    return capped, (reached / total) <= 0.5


def _build_manager(manager: Manager, portfolio: ManagerPortfolio, today: dt.date) -> dict[str, Any]:
    total = portfolio.total_usd
    rows = [
        {
            "issuer": holding.issuer,
            "cusip": holding.cusip,
            "value": holding.value_usd,
            "shares": holding.shares,
            "is_option": holding.is_option,
            "share": (holding.value_usd / total * 100) if total else 0.0,
        }
        for holding in portfolio.holdings
    ]

    count, short_of_majority = _slice_count(rows, total)
    named, rest = rows[:count], rows[count:]
    slices = [dict(row, kind="holding") for row in named]
    if rest:
        rest_value = sum(row["value"] for row in rest)
        slices.append({
            "issuer": None,
            "kind": "rest",
            "count": len(rest),
            "value": rest_value,
            "share": (rest_value / total * 100) if total else 0.0,
        })

    index_value = sum(row["value"] for row in rows if _looks_like_index_product(row["issuer"]))

    # 얼마나 낡았는가. 분기 말 + 45일이 마감이므로 그보다 더 지난 것은 밀린 것이다.
    period = portfolio.period
    lag_days = (today - period).days if period else None

    return {
        "slug": manager.slug,
        "cik": portfolio.cik,
        "filer_name": portfolio.name,
        "fund": {"ko": manager.fund_ko, "en": manager.fund_en},
        "person": {"ko": manager.person_ko, "en": manager.person_en},
        "person_note": (
            {"ko": manager.person_note_ko, "en": manager.person_note_en}
            if manager.person_note_ko else None
        ),
        "form": portfolio.form,
        "filed": portfolio.filed.isoformat() if portfolio.filed else None,
        "period": period.isoformat() if period else None,
        "period_lag_days": lag_days,
        "filing_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(portfolio.cik)}/{portfolio.accession}/"
        ),
        "slices": slices,
        "holdings": rows[:TABLE_ROWS],
        "totals": {
            "value": total,
            "issuers": len(rows),
            "rows": portfolio.row_count,
            "slice_count": count,
            "table_rows": min(TABLE_ROWS, len(rows)),
            "value_scale": portfolio.value_scale,
            "options_share": (portfolio.options_value_usd / total * 100) if total else 0.0,
            "index_share": (index_value / total * 100) if total else 0.0,
            "named_share": sum(row["share"] for row in named),
            "short_of_majority": short_of_majority,
        },
    }


def refresh(provider: SecEdgarProvider | None = None, *, today: dt.date | None = None) -> dict:
    """여섯 신고자를 걷어 한 blob으로 저장한다. 요청 경로에서는 EDGAR를 안 부른다.

    한 명이 실패해도 나머지는 낸다 — 신고가 늦거나 정보표 형식이 낯선 제출자
    하나 때문에 화면 전체가 사라지면 안 된다. 대신 실패한 이름을 payload에
    남겨 화면이 "이 사람은 못 읽었다"를 말할 수 있게 한다.
    """
    _require_lane()
    provider = provider or SecEdgarProvider(user_agent=config.SEC_EDGAR_USER_AGENT)
    today = today or dt.date.today()

    built: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for manager in MANAGERS:
        try:
            portfolio = provider.fetch_latest_13f(manager.cik)
        except (EdgarNotFound, DataUnavailable, DataError, RateLimited) as exc:
            log.warning("13F 실패 %s: %s", manager.slug, exc)
            failed.append({"slug": manager.slug, "reason": type(exc).__name__})
            continue
        built.append(_build_manager(manager, portfolio, today))

    if not built:
        raise DataUnavailable("no 13F portfolio could be read")

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "managers": built,
        "failed": failed,
        "count": len(built),
        "basis_ko": (
            "미국 증권거래위원회에 제출된 13F-HR(분기 기관 보유 신고)을 그대로 옮깁니다. "
            "분기 말 기준이며 45일 안에 제출하면 되므로 현재 보유와 다를 수 있습니다. "
            "이 서식에는 공매도·채권·현금·해외 상장 주식·사모 지분이 들어오지 않으므로 "
            "여기 보이는 것은 자산 전부가 아니라 미국 상장주식 롱 포지션의 구성입니다. "
            "투자 권유가 아닙니다."
        ),
        "basis_en": (
            "Form 13F-HR quarterly institutional holdings, relayed verbatim from the SEC. "
            "Positions are as of quarter end and may be filed up to 45 days later, so they "
            "may differ from current holdings. The form excludes short positions, bonds, "
            "cash, non-US listings and private stakes, so this is the composition of a "
            "US-listed long book, not a whole portfolio. Not investment advice."
        ),
        "source": {
            "provider": data_rights.SEC_EDGAR,
            "provider_name": SEC_PUBLISHER,
            "publisher": SEC_PUBLISHER,
            "publisher_url": SEC_PUBLISHER_URL,
            "url": "https://www.sec.gov/divisions/investment/13ffaq",
            "notice": SEC_RIGHTS_NOTICE_KO,
            "notice_en": SEC_RIGHTS_NOTICE,
        },
        "rights": {"status": "approved", "notice": SEC_RIGHTS_NOTICE_KO},
    }
    store.save_report(CACHE_KEY, payload)
    return {"managers": len(built), "failed": len(failed)}


def get_managers() -> dict:
    """저장된 결과만 읽는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 8)
    if cached is None:
        raise DataUnavailable("13F portfolios not collected yet")
    return cached
