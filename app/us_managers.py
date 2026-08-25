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

#: **payload의 모양이 바뀔 때마다 올린다.**
#:
#: 배치가 채우는 lane은 코드가 배포돼도 화면이 안 바뀐다 — 저장된 blob이 옛
#: 모양 그대로이기 때문이다. 인물 사진을 붙인 날 실제로 그랬다(2026-08-25):
#: 배포는 성공했고 코드도 맞았는데 라이브는 **전원 이니셜**이었고, 원인을 찾는
#: 데 시간이 걸렸다. TTL이 24시간이라 그냥 두면 하루 동안 그 상태다.
#:
#: 캐시 키를 올리는 방법도 있지만 그러면 새 키에 blob이 없어 **다음 수집까지
#: 503**이 된다 — 고치려다 더 오래 비운다. 대신 ingest가 저장된 값과 이 번호를
#: 견줘 다르면 TTL이 남아 있어도 다시 걷게 한다. 화면은 그동안 옛 모양으로나마
#: 계속 뜨고, 다음 주기에 스스로 낫는다.
SCHEMA = 2

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


COMMONS_FILE = "https://commons.wikimedia.org/wiki/File:"


@dataclass(frozen=True)
class Portrait:
    """카드에 놓는 인물 사진과 **그 사진을 쓸 수 있게 하는 조건**.

    출처 표기가 데이터와 함께 다녀야 한다 — 이 저장소가 모든 숫자에 대해 지키는
    규칙을 사진에도 그대로 적용한다. 파일은 `app/static/portraits/`에 담아 자체
    호스팅한다(핫링크하면 읽는 사람의 브라우저가 위키미디어를 때리고, 그건 쿠키를
    심지 않는다는 방침과 결이 다르다).

    `share_alike`가 참이면 **가공본도 같은 라이선스**다. 우리는 원본을 정사각형으로
    자르고 줄였고 그것이 변형(adaptation)에 해당하므로, 표기에 그 사실을 적는다.
    """

    file: str
    artist: str
    licence: str
    licence_url: str
    commons_file: str
    share_alike: bool = False

    @property
    def source_url(self) -> str:
        from urllib.parse import quote
        return COMMONS_FILE + quote(self.commons_file.replace(" ", "_"))


#: 자유 라이선스가 확인된 것만 담는다(조회 2026-08-25, 커먼즈 `extmetadata`).
#:
#: **드러켄밀러와 켄 피셔는 없다.** 드러켄밀러는 커먼즈에 사진이 한 장도 없고,
#: "Ken Fisher"로 나오는 유일한 사진은 **동명이인**이다 — Fisher House Foundation의
#: 켄 피셔로, 미 국방부가 찍어 라이선스는 자유지만 다른 사람이다. 이름만 보고
#: 넣었으면 아무도 눈치채지 못했을 종류의 오류라 적어 둔다. 사진이 없는 사람은
#: 화면이 이니셜로 자리를 채운다.
PORTRAITS: dict[str, Portrait] = {
    "berkshire": Portrait(
        file="/static/portraits/buffett.webp",
        artist="USA International Trade Administration",
        licence="Public domain", licence_url="",
        commons_file="Warren Buffett at the 2015 SelectUSA Investment Summit (cropped).jpg",
    ),
    "pershing": Portrait(
        file="/static/portraits/ackman.webp",
        artist="Senate Democrats",
        licence="CC BY 2.0", licence_url="https://creativecommons.org/licenses/by/2.0",
        commons_file="Valeant Pharmaceuticals' Business Model (headshot).jpg",
    ),
    "ark": Portrait(
        file="/static/portraits/wood.webp",
        artist="Caroline Wood",
        licence="CC BY-SA 4.0", licence_url="https://creativecommons.org/licenses/by-sa/4.0",
        commons_file="Cathie Wood ARK Invest Photo.jpg",
        share_alike=True,
    ),
    "bridgewater": Portrait(
        file="/static/portraits/dalio.webp",
        artist="Web Summit",
        licence="CC BY 2.0", licence_url="https://creativecommons.org/licenses/by/2.0",
        commons_file="Web Summit 2018 - Forum - Day 2, November 7 HM1 7481 (44858045925).jpg",
    ),
}


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


#: 카드에 이름을 적을 신규·청산 종목 수. 나머지는 개수로만 말한다.
NAMED_CHANGES = 3


def _changes(
    current: ManagerPortfolio, previous: ManagerPortfolio | None
) -> dict[str, Any] | None:
    """직전 분기와 견줘 무엇이 바뀌었는지.

    **CUSIP으로 맞춘다.** 이름으로 맞추면 신고자가 표기를 바꿀 때마다 유령
    매매가 생긴다 — 실측(2026-08-25)으로 버크셔가 `BANK AMERICA CORP`를
    `BANK OF AMER CORP`로 고쳐 적었고, 이름 기준으로는 **275억 달러어치를
    전량 매도하고 같은 분기에 새로 산 것**으로 보였다. CUSIP으로 바꾸니 그
    분기의 진짜 변화는 신규 1건·청산 1건이었다.

    **평가액이 아니라 주식수로 잰다.** 주가가 20% 오르면 한 주도 안 사고
    평가액이 20% 는다. 다만 주식수도 완전하지는 않다 — 분할·합병 같은
    기업행위로도 움직인다. 분할을 자동으로 가려내려 해 봤지만 **진짜 거래를
    분할로 오인한다**(브리지워터가 KLA를 3배로 늘린 것을 `x3.02` 분할로
    잡았다). 그래서 가려내지 않고 **주의문으로 밝힌다.**

    목록에서 사라진 것이 곧 매도도 아니다. SEC에 비공개를 신청하면 보유한
    채로 목록에서 빠진다. 그래서 `청산`이라 부르지 않고 `목록에서 빠짐`으로
    적는다.
    """
    if previous is None or not previous.holdings:
        return None

    def keyed(portfolio: ManagerPortfolio) -> dict[str, Any]:
        return {(h.cusip or h.issuer): h for h in portfolio.holdings}

    now, before = keyed(current), keyed(previous)
    added = [k for k in now if k not in before]
    dropped = [k for k in before if k not in now]
    kept = [k for k in now if k in before]

    increased = [k for k in kept if (now[k].shares or 0) > (before[k].shares or 0)]
    decreased = [k for k in kept if (now[k].shares or 0) < (before[k].shares or 0)]

    def name_rows(keys: list[str], source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        ordered = sorted(keys, key=lambda k: -source[k].value_usd)[:limit]
        return [
            {"issuer": source[k].issuer, "value": source[k].value_usd,
             "shares": source[k].shares}
            for k in ordered
        ]

    return {
        "from_period": previous.period.isoformat() if previous.period else None,
        "to_period": current.period.isoformat() if current.period else None,
        "added": name_rows(added, now, NAMED_CHANGES),
        "dropped": name_rows(dropped, before, NAMED_CHANGES),
        "counts": {
            "added": len(added),
            "dropped": len(dropped),
            "increased": len(increased),
            "decreased": len(decreased),
            "unchanged": len(kept) - len(increased) - len(decreased),
        },
    }


def _portrait_payload(slug: str) -> dict[str, Any] | None:
    portrait = PORTRAITS.get(slug)
    if portrait is None:
        return None
    return {
        "file": portrait.file,
        "artist": portrait.artist,
        "licence": portrait.licence,
        "licence_url": portrait.licence_url,
        "source_url": portrait.source_url,
        "share_alike": portrait.share_alike,
    }


def _build_manager(manager: Manager, portfolio: ManagerPortfolio, today: dt.date,
                   previous: ManagerPortfolio | None = None) -> dict[str, Any]:
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
        "portrait": _portrait_payload(manager.slug),
        "changes": _changes(portfolio, previous),
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
            # 두 분기를 걷는다. 직전 분기를 못 읽어도 현재 구성은 낸다 —
            # 변화를 포기하는 것이 화면 전체를 잃는 것보다 낫다.
            recent = provider.fetch_recent_13f(manager.cik, limit=2)
        except (EdgarNotFound, DataUnavailable, DataError, RateLimited) as exc:
            log.warning("13F 실패 %s: %s", manager.slug, exc)
            failed.append({"slug": manager.slug, "reason": type(exc).__name__})
            continue
        portfolio = recent[0]
        previous = recent[1] if len(recent) > 1 else None
        built.append(_build_manager(manager, portfolio, today, previous))

    if not built:
        raise DataUnavailable("no 13F portfolio could be read")

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "schema": SCHEMA,
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
