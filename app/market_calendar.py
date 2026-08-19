"""Curated KRX and NYSE closure calendars.

Clock-based weekday logic alone calls a holiday "open", so the few dates a
year that break that assumption are curated here from official sources, the
same way the economic calendar curates FOMC and BOK meeting dates: facts with
a verified-at date and an annual recheck, not a live feed.

Weekends are not listed — every caller already handles them — so these sets
hold only weekday closures. KRX includes the exchange's year-end closure
(Dec 31), which is an exchange rule rather than a statutory holiday. NYSE
early-close days (day after Thanksgiving, Christmas Eve) are trading days and
are deliberately absent.

Sources (checked 2026-08-19): 관공서의 공휴일에 관한 규정 및 대체공휴일 공표
(2026·2027 설날·추석·부처님오신날은 공표 일자 교차 확인), KRX 연말휴장 관행,
https://www.nyse.com/markets/hours-calendars.
"""

from __future__ import annotations

import datetime as dt

CURATED_VERIFIED_AT = "2026-08-19"
# 2028년 달력은 이때까지 공표분을 확인해 연장한다.
CURATED_RECHECK_AT = "2027-06-30"

# 평일에 떨어지는 KRX 휴장일만 담는다 (주말 제외, 12/31 연말휴장 포함).
KRX_CLOSED: frozenset[str] = frozenset({
    # 2026 남은 기간
    "2026-09-24",  # 추석 연휴
    "2026-09-25",  # 추석
    "2026-10-05",  # 대체공휴일 (개천절 10/3 토)
    "2026-10-09",  # 한글날
    "2026-12-25",  # 성탄절
    "2026-12-31",  # KRX 연말 휴장
    # 2027
    "2027-01-01",  # 신정
    "2027-02-08",  # 설날 연휴
    "2027-02-09",  # 대체공휴일 (설날)
    "2027-03-01",  # 삼일절
    "2027-05-05",  # 어린이날
    "2027-05-13",  # 부처님오신날
    "2027-08-16",  # 대체공휴일 (광복절 8/15 일)
    "2027-09-14",  # 추석 연휴
    "2027-09-15",  # 추석
    "2027-09-16",  # 추석 연휴
    "2027-10-04",  # 대체공휴일 (개천절 10/3 일)
    "2027-10-11",  # 대체공휴일 (한글날 10/9 토)
    "2027-12-27",  # 대체공휴일 (성탄절 12/25 토)
    "2027-12-31",  # KRX 연말 휴장
})

# NYSE 전일 휴장(full closure)만. 단축 거래일은 거래일이므로 넣지 않는다.
NYSE_CLOSED: frozenset[str] = frozenset({
    # 2026 남은 기간
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
    # 2027
    "2027-01-01",  # New Year's Day
    "2027-01-18",  # Martin Luther King, Jr. Day
    "2027-02-15",  # Washington's Birthday
    "2027-03-26",  # Good Friday
    "2027-05-31",  # Memorial Day
    "2027-06-18",  # Juneteenth (observed)
    "2027-07-05",  # Independence Day (observed)
    "2027-09-06",  # Labor Day
    "2027-11-25",  # Thanksgiving
    "2027-12-24",  # Christmas (observed)
})


def krx_closed(date: dt.date) -> bool:
    """True when the date is a curated KRX weekday closure (weekends excluded)."""
    return date.isoformat() in KRX_CLOSED


def nyse_closed(date: dt.date) -> bool:
    return date.isoformat() in NYSE_CLOSED
