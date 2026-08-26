"""경제 캘린더 — FRED 릴리스 일정 + 검증된 정책회의 큐레이션.

두 재료를 섞되 출처를 행마다 구분한다.

* **미국 데이터 발표 일정**은 FRED 릴리스 메타데이터(release/dates)에서
  자동으로 온다 — CPI·고용보고서·GDP·PCE의 예정일이 실측으로 정확했다
  (2026-08-19 검증: CPI 9/11·10/14, 고용 9/4·10/2). 승인된 FRED lane을 타며
  수집은 ingest 배치에서만 돈다.
* **정책회의·연준 행사(FOMC·한국은행 금통위·잭슨홀 심포지엄)**는 FRED에
  쓸 만한 형태가 없어 공식 페이지에서 확인한 날짜를 코드에 박는다. 확인일과
  출처 URL을 데이터에 동봉하고, "직전 회의 전까지 잠정"이라는 기관 문구
  취지를 basis로 전달한다. 분기·연 단위로 얼마 안 되는 날짜라 큐레이션이
  정직한 최소 비용이다.

일정은 예측이 아니라 기관이 공표한 사실이지만 변경될 수 있다 — 그 사실도
응답에 적는다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, store
from .providers.fred import FRED_REQUIRED_NOTICE, FredProvider

log = logging.getLogger(__name__)

CACHE_KEY = "econ_calendar_v1"
WINDOW_DAYS = 180
MAX_EVENTS = 20

# (FRED release_id, 한국어 이름, 영어 이름)
FRED_RELEASES: tuple[tuple[int, str, str], ...] = (
    (10, "미국 CPI", "US CPI"),
    (50, "미국 고용보고서", "US Employment Situation"),
    (53, "미국 GDP", "US GDP"),
    (54, "미국 PCE·개인소득지출", "US Personal Income & Outlays (PCE)"),
)

# 정책회의 — 공식 페이지에서 확인한 날짜만 싣는다. FOMC는 이틀 회의의 둘째 날
# (결과 발표일), 잭슨홀처럼 며칠짜리 행사는 시작일 하루로 싣고 기간을 이름에
# 병기한다. 새 일정이 공표되면 이 표와 확인일을 함께 갱신한다.
CURATED_VERIFIED_AT = "2026-08-26"
FOMC_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BOK_SOURCE = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A"
JACKSON_HOLE_SOURCE = "https://www.kansascityfed.org/research/jackson-hole-economic-symposium/"
CURATED_EVENTS: tuple[dict[str, Any], ...] = (
    {"date": "2026-08-27", "name_ko": "한국은행 금통위 기준금리 결정", "name_en": "Bank of Korea rate decision", "region": "kr", "source_url": BOK_SOURCE},
    {"date": "2026-08-27", "name_ko": "잭슨홀 경제정책 심포지엄 (8/27–29)", "name_en": "Jackson Hole Economic Policy Symposium (Aug 27–29)", "region": "us", "source_url": JACKSON_HOLE_SOURCE},
    {"date": "2026-09-16", "name_ko": "FOMC 정책결정 발표 (회의 9/15–16)", "name_en": "FOMC policy decision (meeting Sep 15–16)", "region": "us", "source_url": FOMC_SOURCE},
    {"date": "2026-10-22", "name_ko": "한국은행 금통위 기준금리 결정", "name_en": "Bank of Korea rate decision", "region": "kr", "source_url": BOK_SOURCE},
    {"date": "2026-10-28", "name_ko": "FOMC 정책결정 발표 (회의 10/27–28)", "name_en": "FOMC policy decision (meeting Oct 27–28)", "region": "us", "source_url": FOMC_SOURCE},
    {"date": "2026-11-26", "name_ko": "한국은행 금통위 기준금리 결정", "name_en": "Bank of Korea rate decision", "region": "kr", "source_url": BOK_SOURCE},
    {"date": "2026-12-09", "name_ko": "FOMC 정책결정 발표 (회의 12/8–9)", "name_en": "FOMC policy decision (meeting Dec 8–9)", "region": "us", "source_url": FOMC_SOURCE},
)


def refresh(provider: FredProvider | None = None, *, today: dt.date | None = None) -> dict:
    """FRED 릴리스 예정일을 받아 저장한다. ingest 배치에서만 부른다."""
    today = today or dt.date.today()
    provider = provider or FredProvider(
        config.FRED_API_KEY, timeout=config.FRED_TIMEOUT, retries=config.FRED_RETRIES
    )
    releases = {}
    for release_id, name_ko, name_en in FRED_RELEASES:
        dates = provider.fetch_release_dates(
            release_id, start=today, end=today + dt.timedelta(days=WINDOW_DAYS)
        )
        releases[str(release_id)] = {"name_ko": name_ko, "name_en": name_en, "dates": dates}
    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "releases": releases,
    }
    store.save_report(CACHE_KEY, payload)
    return {"releases": len(releases), "dates": sum(len(r["dates"]) for r in releases.values())}


def build_calendar(today: dt.date | None = None) -> dict[str, Any]:
    """저장된 릴리스 일정과 큐레이션을 합쳐 다가오는 이벤트로 편다."""
    today = today or dt.date.today()
    cutoff = today.isoformat()
    events: list[dict[str, Any]] = []

    for event in CURATED_EVENTS:
        if event["date"] >= cutoff:
            events.append({
                "date": event["date"],
                "name": {"ko": event["name_ko"], "en": event["name_en"]},
                "region": event["region"],
                "kind": "policy",
                "source_url": event["source_url"],
                "provider": "curated",
            })

    blob = store.load_report(CACHE_KEY, config.REPORT_TTL * 2) or {}
    for release_id, release in (blob.get("releases") or {}).items():
        for date in release.get("dates") or []:
            if date >= cutoff:
                events.append({
                    "date": date,
                    "name": {"ko": release.get("name_ko"), "en": release.get("name_en")},
                    "region": "us",
                    "kind": "release",
                    "source_url": f"https://fred.stlouisfed.org/release?rid={release_id}",
                    "provider": "fred",
                })

    events.sort(key=lambda item: (item["date"], item["name"]["en"] or ""))
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "as_of": today.isoformat(),
        "events": events[:MAX_EVENTS],
        "curated_verified_at": CURATED_VERIFIED_AT,
        "basis_ko": (
            "발표 일정은 기관이 공표한 예정일이며 변경될 수 있습니다. 미국 데이터 "
            "발표일은 FRED 릴리스 일정에서, FOMC·금통위·잭슨홀 날짜는 각 기관 공식 "
            f"페이지에서 가져왔습니다(확인일 {CURATED_VERIFIED_AT}). FOMC 일정은 "
            "직전 회의 전까지 잠정입니다."
        ),
        "basis_en": (
            "Scheduled dates as announced by the institutions; they can change. US "
            "data-release dates come from FRED release metadata, and FOMC/BOK/Jackson "
            f"Hole dates from the official calendars (verified {CURATED_VERIFIED_AT}). "
            "FOMC dates are tentative until confirmed at the preceding meeting."
        ),
        "source": {
            "fred_notice": FRED_REQUIRED_NOTICE,
            "fomc_url": FOMC_SOURCE,
            "bok_url": BOK_SOURCE,
            "jackson_hole_url": JACKSON_HOLE_SOURCE,
        },
    }
