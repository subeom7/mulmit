"""환경변수 기반 설정.

배포 환경에서 코드 수정 없이 조정할 수 있도록 캐시 TTL, 저장소 주소,
시뮬레이션 기본값을 전부 환경변수로 뺐다.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- 저장소 -----------------------------------------------------------------
# 로컬은 SQLite라 아무 준비 없이 돌아간다. 배포에선 DATABASE_URL로 Postgres를
# 주입한다. 같은 SQLAlchemy Core 코드가 양쪽에서 그대로 돈다.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / ".data"))
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'stock.db'}"

# --- 데이터 신선도 -----------------------------------------------------------
# 일봉은 하루 한 번만 바뀐다. 이 시간이 지난 티커를 배치가 다시 받아온다.
PRICE_MAX_AGE = _int("PRICE_MAX_AGE", 60 * 60 * 20)
INFO_MAX_AGE = _int("INFO_MAX_AGE", 60 * 60 * 24 * 3)
MACRO_MAX_AGE = _int("MACRO_MAX_AGE", 60 * 60 * 12)
# FRED adapter is kept for licensed/private evaluation only. Current FRED API
# terms restrict storing/caching API content for redistribution, so public
# deployments must remain disabled unless written permission is obtained.
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
FRED_ENABLED = _bool("FRED_ENABLED", False)
FRED_MAX_AGE = _int("FRED_MAX_AGE", 60 * 60 * 6)
FRED_TIMEOUT = _float("FRED_TIMEOUT", 15.0)
FRED_RETRIES = _int("FRED_RETRIES", 2)
FRED_INGEST_DELAY = _float("FRED_INGEST_DELAY", 0.1)
# U.S. Bureau of Labor Statistics. Their terms state outright that everything
# BLS publishes is in the public domain and free to use without permission, in
# return for citing BLS as the source. https://www.bls.gov/bls/linksite.htm
# A key is optional: it raises the daily allowance from 25 to 500 queries and
# the window from ten years to twenty.
BLS_ENABLED = _bool("BLS_ENABLED", False)
BLS_API_KEY = os.environ.get("BLS_API_KEY", "").strip()
BLS_TIMEOUT = _float("BLS_TIMEOUT", 20.0)
BLS_RETRIES = _int("BLS_RETRIES", 2)
BLS_MAX_AGE = _int("BLS_MAX_AGE", 60 * 60 * 12)

# Board of Governors statistical releases (H.15 rates, later H.10 FX and more).
# The Board is retiring its Data Download Program in favour of FRED, which we
# cannot use, so this reads the release-page XML archives the transition notice
# says will remain. https://www.federalreserve.gov/data/data-download-fred-information.htm
FEDBOARD_ENABLED = _bool("FEDBOARD_ENABLED", False)
FEDBOARD_TIMEOUT = _float("FEDBOARD_TIMEOUT", 30.0)
FEDBOARD_RETRIES = _int("FEDBOARD_RETRIES", 2)
FEDBOARD_REQUEST_INTERVAL = _float("FEDBOARD_REQUEST_INTERVAL", 0.5)
# The archives are multi-megabyte and the releases update daily at most, so a
# long refresh window keeps one download serving every series in it.
FEDBOARD_MAX_AGE = _int("FEDBOARD_MAX_AGE", 60 * 60 * 4)  # H.15 일별 발행을 T+1 새벽에 집도록
FEDBOARD_HISTORY_DAYS = _int("FEDBOARD_HISTORY_DAYS", 366 * 25)

# Federal Reserve Bank of New York markets API (SOFR, EFFR, overnight RRP).
# Their Terms of Use grant automated access plus the right to download, store,
# copy, distribute and derive from the content for business purposes, on the
# condition that the prescribed source identifier travels with it. No key.
# https://www.newyorkfed.org/privacy/termsofuse
NYFED_ENABLED = _bool("NYFED_ENABLED", False)
NYFED_TIMEOUT = _float("NYFED_TIMEOUT", 15.0)
NYFED_RETRIES = _int("NYFED_RETRIES", 2)
NYFED_REQUEST_INTERVAL = _float("NYFED_REQUEST_INTERVAL", 0.2)
NYFED_MAX_AGE = _int("NYFED_MAX_AGE", 60 * 60 * 6)
# How much history to request per refresh. SOFR starts in 2018, so ten years
# covers the full published series without asking for more than exists.
NYFED_HISTORY_DAYS = _int("NYFED_HISTORY_DAYS", 366 * 10)

# SEC EDGAR insider-ownership filings (Forms 3/4/5). EDGAR is a public federal
# disclosure system and the SEC states anyone may access and download it for
# free, but automated access has hard operating rules: a declared User-Agent
# carrying a real contact address, and at most 10 requests/second across all
# machines. The contact address is deployment-specific and is never committed,
# so an unset SEC_EDGAR_USER_AGENT keeps the lane closed.
# https://www.sec.gov/os/accessing-edgar-data
SEC_EDGAR_ENABLED = _bool("SEC_EDGAR_ENABLED", False)
SEC_EDGAR_USER_AGENT = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
SEC_EDGAR_TIMEOUT = _float("SEC_EDGAR_TIMEOUT", 15.0)
SEC_EDGAR_RETRIES = _int("SEC_EDGAR_RETRIES", 2)
# 0.15s between requests is ~6.7/s, comfortably under the published 10/s cap
# even when a retry lands next to a scheduled call.
SEC_EDGAR_REQUEST_INTERVAL = _float("SEC_EDGAR_REQUEST_INTERVAL", 0.15)
SEC_EDGAR_MAX_AGE = _int("SEC_EDGAR_MAX_AGE", 60 * 60 * 12)
# Filings pulled per company per refresh. Form 4s are small but numerous.
SEC_EDGAR_FILING_LIMIT = _int("SEC_EDGAR_FILING_LIMIT", 40)
# Companies refreshed per batch, so one cycle cannot monopolise the rate budget.
SEC_EDGAR_BATCH_SIZE = _int("SEC_EDGAR_BATCH_SIZE", 5)
SEC_EDGAR_TICKERS = [
    t.strip().upper()
    for t in os.environ.get("SEC_EDGAR_TICKERS", "AAPL,MSFT,NVDA,GOOGL,TSLA").split(",")
    if t.strip()
]

# Hyperliquid HIP-3 / trade.xyz values are reachable without a key, but public
# reachability is not a redistribution right. Written confirmation is still
# pending, so the serving gate defaults to closed and a deployment has to opt in
# explicitly (and record that decision in docs/DATA_SOURCE_REGISTER.md).
HIP3_PUBLIC_DISPLAY_ENABLED = _bool("HIP3_PUBLIC_DISPLAY_ENABLED", False)
# Stored daily history for the same cards (candleSnapshot 1d). Its own gate on
# top of the display gate: keeping a year of another venue's closes is a bigger
# footprint than relaying one mark, so a deployment opts in explicitly and
# records the decision (DS-2026-001, revised 2026-08-21). Both default closed.
HIP3_HISTORY_ENABLED = _bool("HIP3_HISTORY_ENABLED", False)
HIP3_HISTORY_MAX_AGE = _int("HIP3_HISTORY_MAX_AGE", 60 * 60 * 6)
HIP3_HISTORY_DAYS = _int("HIP3_HISTORY_DAYS", 366)
HIP3_HISTORY_TIMEOUT = _float("HIP3_HISTORY_TIMEOUT", 10.0)
# Financial Services Commission end-of-day data on data.go.kr. The three
# datasets used here are registered with 이용허락범위 "제한 없음" — the portal's
# widest licence tier — which is a different and broader grant than the KRX
# OPEN API terms below. Published the next business day at 13:00 KST, so this
# is never a live quote. https://www.data.go.kr/data/15094808/openapi.do
# 한국은행 ECOS — 한국 거시 lane (FRED의 한국 대칭). 인증키 약관 확인 전까지
# 기본 꺼짐(fail-closed)으로 배포된다.
ECOS_ENABLED = _bool("ECOS_ENABLED", False)
ECOS_API_KEY = os.environ.get("ECOS_API_KEY", "")
ECOS_TIMEOUT = _float("ECOS_TIMEOUT", 15.0)
ECOS_RETRIES = _int("ECOS_RETRIES", 2)
ECOS_REQUEST_INTERVAL = _float("ECOS_REQUEST_INTERVAL", 0.2)
ECOS_MAX_AGE = _int("ECOS_MAX_AGE", 60 * 60 * 6)
ECOS_HISTORY_DAYS = _int("ECOS_HISTORY_DAYS", 366 * 10)

# GDELT 뉴스 메타데이터 lane. 약관상 상업·재배포 명시 허용(§6.1) — 게이트는
# lane 규율의 일관성 때문에 두고, 배포에서 켠다.
GDELT_ENABLED = _bool("GDELT_ENABLED", False)
GDELT_TIMEOUT = _float("GDELT_TIMEOUT", 15.0)
GDELT_RETRIES = _int("GDELT_RETRIES", 1)
GDELT_MAX_AGE = _int("GDELT_MAX_AGE", 60 * 15)  # 벌크 파일 발행 주기와 동일

# 정부 보도자료 RSS (금융위·기재부) — 제목·기관·링크만. 뉴스의 한국어 축.
KR_PRESS_ENABLED = _bool("KR_PRESS_ENABLED", False)
KR_PRESS_TIMEOUT = _float("KR_PRESS_TIMEOUT", 15.0)
KR_PRESS_MAX_AGE = _int("KR_PRESS_MAX_AGE", 60 * 15)

FSC_ENABLED = _bool("FSC_ENABLED", False)
FSC_API_KEY = os.environ.get("FSC_API_KEY", "").strip()
FSC_TIMEOUT = _float("FSC_TIMEOUT", 20.0)
FSC_RETRIES = _int("FSC_RETRIES", 2)
FSC_REQUEST_INTERVAL = _float("FSC_REQUEST_INTERVAL", 0.2)
# One publication a day means a long refresh window costs nothing and keeps the
# daily call allowance clear.
FSC_MAX_AGE = _int("FSC_MAX_AGE", 60 * 60 * 12)
FSC_HISTORY_DAYS = _int("FSC_HISTORY_DAYS", 366 * 5)

# 금융감독원 Open DART — 임원·주요주주 특정증권등 소유상황 보고(한국판 Form 4).
# 법정 공시를 개방하는 공공기관 API이며, 이용약관은 재배포를 금지하지 않고
# 허용량 제한(홈페이지 게시)을 둔다. 키는 배포별 발급이라 커밋하지 않는다.
# https://opendart.fss.or.kr/intro/terms.do
DART_ENABLED = _bool("DART_ENABLED", False)
DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()
DART_TIMEOUT = _float("DART_TIMEOUT", 20.0)
DART_RETRIES = _int("DART_RETRIES", 2)
DART_REQUEST_INTERVAL = _float("DART_REQUEST_INTERVAL", 0.25)
# 보고서 목록 캐시. 공시는 수시 제출이라 반나절 신선도면 충분하다.
DART_MAX_AGE = _int("DART_MAX_AGE", 60 * 60 * 12)
# 주요사항보고 속보 피드는 공시 lane과 별개 주기로 더 자주 돈다 (요청 수 ~3/회).
KR_EVENTS_MAX_AGE = _int("KR_EVENTS_MAX_AGE", 60 * 15)
# 법인코드 매핑(zip)은 거의 안 바뀐다.
DART_CORP_MAX_AGE = _int("DART_CORP_MAX_AGE", 60 * 60 * 24 * 7)

# 미 하원 PTR(STOCK Act) — 법정 공시 relay. 키는 없고 게이트만 있다.
US_PTR_ENABLED = _bool("US_PTR_ENABLED", False)
US_PTR_TIMEOUT = _float("US_PTR_TIMEOUT", 30.0)
US_PTR_RETRIES = _int("US_PTR_RETRIES", 2)
US_PTR_REQUEST_INTERVAL = _float("US_PTR_REQUEST_INTERVAL", 1.0)
US_PTR_MAX_AGE = _int("US_PTR_MAX_AGE", 60 * 60 * 6)

# KRX OPEN API must remain disabled until KRX approves the exact public use
# case. Possessing a key alone does not grant redistribution rights. The FSC
# lane above does not change this: it is a separate grant over a separate,
# next-day dataset, not KRX approval arriving by another route.
KRX_ENABLED = _bool("KRX_ENABLED", False)
KRX_API_KEY = os.environ.get("KRX_API_KEY", "").strip()
KRX_TIMEOUT = _float("KRX_TIMEOUT", 15.0)
KRX_RETRIES = _int("KRX_RETRIES", 2)
# 조립된 리포트 응답 캐시. 시드가 고정이라 같은 입력이면 결과가 같다.
REPORT_TTL = _int("REPORT_TTL", 60 * 60 * 24)
# 없는 티커를 기억해 두는 시간(같은 오타로 야후를 계속 두드리지 않도록)
NEGATIVE_TTL = _int("NEGATIVE_TTL", 60 * 60 * 6)

# --- 수집 배치 ---------------------------------------------------------------
INGEST_ENABLED = _bool("INGEST_ENABLED", True)
# 스케줄러 "틱"(초). 틱은 샘플링 주기일 뿐이고 실제 갱신 주기는 lane별
# max-age가 정한다 — 뉴스류(GDELT·보도자료·주요사항)는 15분, 거시·공시류는
# 각자의 시간 단위 게이트로 틱 대부분을 fresh 스킵한다.
INGEST_INTERVAL = _int("INGEST_INTERVAL", 60 * 15)
INGEST_BATCH_SIZE = _int("INGEST_BATCH_SIZE", 40)  # 1회 실행당 최대 티커 수
INGEST_DELAY = _float("INGEST_DELAY", 1.5)  # 티커 사이 간격(초). 야후 배려용
# 레이트리밋을 맞으면 지수적으로 물러선다. 막힌 상태에서 계속 노크하면
# 밴이 풀리지 않고 오히려 연장된다. 상한 기본 6시간.
INGEST_BACKOFF_MAX = _int("INGEST_BACKOFF_MAX", 60 * 60 * 6)
# 아무도 조회하지 않아도 항상 최신으로 유지할 티커(시장지수·금리는 필수)
SEED_TICKERS = [
    t.strip().upper()
    for t in os.environ.get("SEED_TICKERS", "AAPL,MSFT,SPY,QQQ").split(",")
    if t.strip()
]
# S&P 500의 11개 GICS 섹터를 추종하는 Select Sector SPDR ETF.
# 사용자 시드와 분리해 두어 SEED_TICKERS를 바꿔도 섹터 히트맵은 계속 갱신한다.
SECTOR_ETF_TICKERS = (
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)

# --- 요청 제한 ---------------------------------------------------------------
# 몬테카를로는 CPU를 쓴다. 캐시를 우회하는 파라미터 조합으로 서버를 갈아넣는
# 걸 막는다. 캐시 히트도 세지만 그쪽은 어차피 싸다.
RATE_LIMIT = os.environ.get("RATE_LIMIT", "60/minute")
RATE_LIMIT_HEAVY = os.environ.get("RATE_LIMIT_HEAVY", "20/minute")

# --- 분석 기본값 -------------------------------------------------------------
MARKET_TICKER = os.environ.get("MARKET_TICKER", "^GSPC")  # S&P 500
RISKFREE_TICKER = os.environ.get("RISKFREE_TICKER", "^TNX")  # 미 10년물
FALLBACK_RISKFREE = _float("FALLBACK_RISKFREE", 0.042)  # ^TNX 조회 실패 시
EXPECTED_MARKET_RETURN = _float("EXPECTED_MARKET_RETURN", 0.08)  # 시장 기대수익률
TRADING_DAYS = 252

# 회귀분석/시뮬레이션에 쓸 과거 데이터 길이(년)
DEFAULT_LOOKBACK_YEARS = _int("DEFAULT_LOOKBACK_YEARS", 10)

# --- 미래 MDD 시뮬레이션 -----------------------------------------------------
DEFAULT_HORIZON_MONTHS = _int("DEFAULT_HORIZON_MONTHS", 12)  # 예측 구간(개월)
DEFAULT_SIMS = _int("DEFAULT_SIMS", 5000)
MAX_SIMS = _int("MAX_SIMS", 50000)
BLOCK_SIZE = _int("BLOCK_SIZE", 20)  # 블록 부트스트랩 블록 길이(거래일)
SIM_CHUNK = _int("SIM_CHUNK", 1000)  # 메모리 절약용 청크 크기
RANDOM_SEED = _int("RANDOM_SEED", 20260801)  # 재현 가능한 결과

# --- 데이터 공급자 -----------------------------------------------------------
# Yahoo/yfinance 경로는 공개 재배포 권리가 확인되지 않은 레거시 기능이다.
# 사설/개발 환경에서 명시적으로 opt-in한 경우에만 사용한다.
LEGACY_PRICE_DATA_ENABLED = _bool("LEGACY_PRICE_DATA_ENABLED", False)
# 유료 API로 갈아탈 때 여기만 바꾼다. providers/__init__.py 참고.
PROVIDER = os.environ.get("PROVIDER", "yahoo")
