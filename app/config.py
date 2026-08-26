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

# Office of Financial Research (U.S. Treasury) Financial Stress Index. A
# federal work: the OFR's Legal Notices claim no copyright and request credit;
# no Treasury seal/emblem, no implied endorsement. One daily CSV serves the
# composite and its five categories. https://www.financialresearch.gov/legal-notices/
OFR_ENABLED = _bool("OFR_ENABLED", False)
OFR_TIMEOUT = _float("OFR_TIMEOUT", 30.0)
OFR_RETRIES = _int("OFR_RETRIES", 2)
# Published once per business day with a two-business-day lag; 6h keeps the
# morning release within the same day without re-downloading the file hourly.
OFR_MAX_AGE = _int("OFR_MAX_AGE", 60 * 60 * 6)
OFR_HISTORY_DAYS = _int("OFR_HISTORY_DAYS", 366 * 10)

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

# 13F는 분기 서식이고 제출은 분기 말 + 45일 안이다. 하루에 한 번이면
# 넘치도록 촘촘하다 - 더 자주 돌면 EDGAR에 폐를 끼치고 얻는 것이 없다.
US_MANAGERS_MAX_AGE = _int("US_MANAGERS_MAX_AGE", 60 * 60 * 24)
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
# --- 크립토 섹션 (docs/PLAN_CRYPTO_SECTION.md) ---------------------------------
# Page and /api/crypto/* rollout switch. Hyperliquid's own perpetuals ride the
# HIP-3 display gate above (same API, same posture: perpetual references, not
# spot quotes); this flag only decides whether the section is exposed at all.
CRYPTO_SECTION_ENABLED = _bool("CRYPTO_SECTION_ENABLED", False)
# Cached half of the per-coin regime read (daily candles for the curated coins);
# funding is always scored live, so this only paces the candle calls.
CRYPTO_HEAT_MAX_AGE = _int("CRYPTO_HEAT_MAX_AGE", 60 * 30)
# alternative.me Crypto Fear & Greed Index. The publisher's terms allow
# commercial use "as long as the attribution is given right next to the display
# of the data" (accessed 2026-08-21); the payload carries that attribution and
# the UI must keep it beside the value. Daily index, polled hourly by ingest.
# https://alternative.me/crypto/fear-and-greed-index/
ALTERNATIVE_ME_ENABLED = _bool("ALTERNATIVE_ME_ENABLED", False)
ALTERNATIVE_ME_TIMEOUT = _float("ALTERNATIVE_ME_TIMEOUT", 15.0)
ALTERNATIVE_ME_RETRIES = _int("ALTERNATIVE_ME_RETRIES", 2)
ALTERNATIVE_ME_MAX_AGE = _int("ALTERNATIVE_ME_MAX_AGE", 60 * 60)
# CoinMarketCap global metrics (BTC/ETH dominance, total market cap). Keyed.
# Pricing page (2026-08-21): "Commercial use rights — the free Basic tier
# included", 15,000 credits/month, 50 req/min; the Commercial Terms require
# attribution next to the data and forbid standalone redistribution. The
# operator confirms the exact scope when issuing the key. The key is needed by
# ingest only; web serves the stored blob when CMC_ENABLED is on.
# https://coinmarketcap.com/api/pricing/
CMC_ENABLED = _bool("CMC_ENABLED", False)
CMC_API_KEY = os.environ.get("CMC_API_KEY", "").strip()
CMC_TIMEOUT = _float("CMC_TIMEOUT", 15.0)
CMC_RETRIES = _int("CMC_RETRIES", 2)
# 15 minutes ≈ 2,900 credits/month, a fifth of the Basic allowance.
CMC_MAX_AGE = _int("CMC_MAX_AGE", 60 * 15)
# USDT/USDC circulating supply (quotes/latest, one credit per call); hourly by default.
CMC_STABLECOIN_MAX_AGE = _int("CMC_STABLECOIN_MAX_AGE", 60 * 60)
CMC_ATTRIBUTION_TEXT = os.environ.get("CMC_ATTRIBUTION_TEXT", "Data provided by CoinMarketCap").strip()
# Upbit (Dunamu) KRW quotations for the kimchi premium. No key; public quotation
# API, per-IP limits. The Open API terms (2023-12-15) §5 assert copyright over the
# data and neither permit nor forbid public redisplay, so the lane stays
# `pending_rights` and off until a written answer or a recorded operator risk
# acceptance (docs/DATA_SOURCE_REGISTER.md §3.19) switches it on.
UPBIT_ENABLED = _bool("UPBIT_ENABLED", False)
UPBIT_TIMEOUT = _float("UPBIT_TIMEOUT", 5.0)
UPBIT_RETRIES = _int("UPBIT_RETRIES", 1)
# Gas / fee strip. Public chain state read through the operator's OWN RPC
# provider account (Alchemy/Infura free tier …) — URLs (which embed the key)
# come only from env and are never echoed. No public endpoint is baked in: the
# ones checked either forbid redistribution (PublicNode ToS), are "not suitable
# for production traffic" (Base docs) or need a paid plan (register §3.21).
CHAIN_GAS_ENABLED = _bool("CHAIN_GAS_ENABLED", False)
# Coinalyze liquidation/open-interest lane. Written permission is on file
# (register §3.27); the key is generated on the operator's Coinalyze account
# and lives in the ingest process only.
# 네이버 데이터랩 통합검색어 트렌드 — 종목 검색 관심도(등록부 §6.7). 판정 요지:
# 데이터랩에는 개별 API 특약이 **없다**. 뉴스 검색을 기각시킨 특약(독립 노출·삽입
# 금지·무조건 저장 금지·검색결과 페이지 광고 금지)은 검색 API 특약 안에만 있고,
# 현행 AI·Naver API 약관 v6.0의 개별 특약은 지도·파파고·CLOVA 셋뿐이다.
# 요청 경로에서만 돌고 **저장하지 않는다** — 창 전체가 요청마다 오므로 이력이 필요 없다.
# 쿼터는 NCP 구독 실측 월 50,000회. 키는 콘솔의 애플리케이션에서 발급한다.
NAVER_DATALAB_ENABLED = _bool("NAVER_DATALAB_ENABLED", False)
NAVER_DATALAB_CLIENT_ID = os.environ.get("NAVER_DATALAB_CLIENT_ID", "").strip()
NAVER_DATALAB_CLIENT_SECRET = os.environ.get("NAVER_DATALAB_CLIENT_SECRET", "").strip()
NAVER_DATALAB_TIMEOUT = _float("NAVER_DATALAB_TIMEOUT", 8.0)
NAVER_DATALAB_RETRIES = _int("NAVER_DATALAB_RETRIES", 1)
# 값은 하루 단위로만 바뀐다. 6시간이면 워치리스트 한 벌이 하루 4번 × 묶음 수다.
NAVER_DATALAB_MAX_AGE = _int("NAVER_DATALAB_MAX_AGE", 6 * 60 * 60)
# 볼 종목. `코드` 또는 `코드=검색어` 쉼표 목록. 비어 있으면 lane은 닫힌다.
# 검색어 덮어쓰기는 이름이 회사만 가리키지 않는 종목을 위한 것이다 —
# `NAVER`나 `카카오`를 검색한 사람 대부분은 주식을 보러 온 것이 아니다.
# 로스터 전체를 도는 것은
# 쿼터가 아니라 뜻에서 틀린다(거래 없는 종목의 검색 추이는 잡음이다).
NAVER_DATALAB_WATCHLIST = os.environ.get("NAVER_DATALAB_WATCHLIST", "").strip()
# 요청을 잇는 앵커. 모든 요청에 함께 넣어, 같은 날 앵커 대비 비율로 종목 간
# 수준을 견준다(정규화가 분자·분모에서 함께 사라진다). 검색량이 가장 큰 종목을
# 두어야 작은 종목의 값이 반올림에 뭉개지지 않는다. 워치리스트에 없으면 첫 항목.
NAVER_DATALAB_ANCHOR = os.environ.get("NAVER_DATALAB_ANCHOR", "005930").strip().upper()

COINALYZE_ENABLED = _bool("COINALYZE_ENABLED", False)
COINALYZE_API_KEY = os.environ.get("COINALYZE_API_KEY", "").strip()
CHAIN_RPC_ETHEREUM_URL = os.environ.get("CHAIN_RPC_ETHEREUM_URL", "").strip()
CHAIN_RPC_BASE_URL = os.environ.get("CHAIN_RPC_BASE_URL", "").strip()
CHAIN_RPC_ARBITRUM_URL = os.environ.get("CHAIN_RPC_ARBITRUM_URL", "").strip()
CHAIN_RPC_PROVIDER_NAME = os.environ.get("CHAIN_RPC_PROVIDER_NAME", "").strip()
CHAIN_RPC_TIMEOUT = _float("CHAIN_RPC_TIMEOUT", 6.0)

# --- Bio section (ROADMAP #8): ClinicalTrials.gov watchlist + openFDA approvals. Gates default off.
BIO_SECTION_ENABLED = _bool("BIO_SECTION_ENABLED", False)
CLINICALTRIALS_ENABLED = _bool("CLINICALTRIALS_ENABLED", False)
CLINICALTRIALS_TIMEOUT = _float("CLINICALTRIALS_TIMEOUT", 20.0)
CLINICALTRIALS_RETRIES = _int("CLINICALTRIALS_RETRIES", 2)
CLINICALTRIALS_MAX_AGE = _int("CLINICALTRIALS_MAX_AGE", 60 * 60 * 6)
CLINICALTRIALS_PACE_SECONDS = _float("CLINICALTRIALS_PACE_SECONDS", 0.6)
CLINICALTRIALS_PAGE_SIZE = _int("CLINICALTRIALS_PAGE_SIZE", 25)
OPENFDA_ENABLED = _bool("OPENFDA_ENABLED", False)
OPENFDA_API_KEY = os.environ.get("OPENFDA_API_KEY", "").strip()  # optional, ingest only
OPENFDA_TIMEOUT = _float("OPENFDA_TIMEOUT", 20.0)
OPENFDA_RETRIES = _int("OPENFDA_RETRIES", 2)
OPENFDA_MAX_AGE = _int("OPENFDA_MAX_AGE", 60 * 60 * 24)
OPENFDA_WINDOW_DAYS = _int("OPENFDA_WINDOW_DAYS", 60)
# Phase 2: PubMed citations for watched trials (NCBI E-utilities) and FDA advisory-committee notices (Federal Register).
PUBMED_ENABLED = _bool("PUBMED_ENABLED", False)
NCBI_TOOL = os.environ.get("NCBI_TOOL", "mulmit").strip() or "mulmit"
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "").strip()  # contact for NCBI's usage policy; ingest only
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()  # optional (10 req/s instead of 3); ingest only
PUBMED_TIMEOUT = _float("PUBMED_TIMEOUT", 20.0)
PUBMED_RETRIES = _int("PUBMED_RETRIES", 2)
PUBMED_MAX_AGE = _int("PUBMED_MAX_AGE", 60 * 60 * 24)
PUBMED_PACE_SECONDS = _float("PUBMED_PACE_SECONDS", 0.4)
PUBMED_OFFPEAK_ONLY = _bool("PUBMED_OFFPEAK_ONLY", True)
FEDERAL_REGISTER_ENABLED = _bool("FEDERAL_REGISTER_ENABLED", False)
FEDERAL_REGISTER_TIMEOUT = _float("FEDERAL_REGISTER_TIMEOUT", 20.0)
FEDERAL_REGISTER_RETRIES = _int("FEDERAL_REGISTER_RETRIES", 2)
ADCOMM_MAX_AGE = _int("ADCOMM_MAX_AGE", 60 * 60 * 6)
# MFDS drug product permits (data.go.kr dataset 15095677). One service key per data.go.kr account,
# so MFDS_API_KEY falls back to the FSC key when not set separately. Ingest only.
MFDS_ENABLED = _bool("MFDS_ENABLED", False)
MFDS_API_KEY = os.environ.get("MFDS_API_KEY", "").strip() or os.environ.get("FSC_API_KEY", "").strip()
MFDS_TIMEOUT = _float("MFDS_TIMEOUT", 20.0)
MFDS_RETRIES = _int("MFDS_RETRIES", 2)
MFDS_MAX_AGE = _int("MFDS_MAX_AGE", 60 * 60 * 24)
MFDS_WINDOW_DAYS = _int("MFDS_WINDOW_DAYS", 30)
MFDS_PACE_SECONDS = _float("MFDS_PACE_SECONDS", 0.2)

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

# 유튜브 뉴스 영상 lane — 못 박은 채널의 최근 업로드 목록(제목·채널·시각·링크).
# 썸네일은 받지 않고, 재생을 누르기 전에는 유튜브로 요청이 나가지 않는다.
# 수집은 ingest 전용. 등록부 §3.28 / DS-2026-020.
YOUTUBE_ENABLED = _bool("YOUTUBE_ENABLED", False)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
YOUTUBE_TIMEOUT = _float("YOUTUBE_TIMEOUT", 15.0)
YOUTUBE_MAX_AGE = _int("YOUTUBE_MAX_AGE", 60 * 30)

FSC_ENABLED = _bool("FSC_ENABLED", False)
FSC_API_KEY = os.environ.get("FSC_API_KEY", "").strip()
FSC_TIMEOUT = _float("FSC_TIMEOUT", 20.0)
FSC_RETRIES = _int("FSC_RETRIES", 2)
FSC_REQUEST_INTERVAL = _float("FSC_REQUEST_INTERVAL", 0.2)
# One publication a day means a long refresh window costs nothing and keeps the
# daily call allowance clear.
FSC_MAX_AGE = _int("FSC_MAX_AGE", 60 * 60 * 12)
# 개별 종목의 종가 시리즈는 스냅샷과 수명이 다르다.
#
# `FSC_MAX_AGE` 하나가 로스터·지수·ETF 스냅샷과 종목 시리즈를 함께 지배했다.
# 운영에서는 스냅샷을 빨리 받으려고 이 값을 1시간으로 낮춰 두었는데, 그 바람에
# 종목 시리즈도 매시간 만료됐다 — 같은 종목을 한 시간 뒤에 다시 열면 5년치를
# 처음부터 다시 받는다.
#
# 실측 2026-08-24(서버): 콜드 3.0초 중 **상류 호출이 3.05초**, DB 저장 0.22초,
# 읽기 0.01초. 줄일 수 있는 지역 비용이 없다. 행 수에 비례하고(1,236행 2.97초,
# 729행 2.03초, 245행 0.67초) 호출은 언제나 1회다.
#
# 시리즈는 확정 종가라 장중에 바뀌지 않으므로, 수명을 따로 준다. 6시간이면
# 아침 발행을 그날 안에 받으면서 콜드 조회는 6분의 1로 준다. 이 파일의 원래
# 기본값이 12시간이었으니 새로 만든 위험도 아니다.
FSC_SERIES_MAX_AGE = _int("FSC_SERIES_MAX_AGE", 60 * 60 * 6)
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
# DART 재무·소유보고 사전수집. 종목 하나당 DART 호출이 3~4번(재무 2~3 + 소유보고 1).
# 이게 없으면 그 두 블록은 **사람이 페이지를 열어야만** 채워진다 — 2026-08-26에
# 크롤러 요청이 그 일을 하고 있었고(콜드 3.5초의 정체), 그걸 막으면서 채우는
# 경로까지 같이 사라졌다.
KR_DART_PRECOLLECT_PER_RUN = _int("KR_DART_PRECOLLECT_PER_RUN", 8)
# 커버리지 채우기 허용치. `DART_MAX_AGE`(서빙 신선도)와 **다른 질문**이다.
#
# 처음에 하나로 썼다가 예산이 안 맞았다(실측 2026-08-26): 12시간 만료면 640건을
# 하루 두 번 = 1,280건 갱신해야 하는데 예산은 8×96 = 768건이라, 신규 확보와
# 갱신이 서로 예산을 뺏으며 60% 언저리에서 정체한다.
#
# 연간 재무제표는 분기에 한 번 바뀌는 값이다. 커버리지 목적에서 사흘 지난 값은
# **없는 것보다 낫다**. 3일이면 640/3 = 213건/일이라 예산 안에 넉넉히 들어온다.
# 사용자가 보는 신선도 기준은 DART_MAX_AGE 그대로다.
KR_DART_COVERAGE_MAX_AGE = _int("KR_DART_COVERAGE_MAX_AGE", 60 * 60 * 24 * 3)

# 미 하원 PTR(STOCK Act) — 법정 공시 relay. 키는 없고 게이트만 있다.
US_PTR_ENABLED = _bool("US_PTR_ENABLED", False)
US_PTR_TIMEOUT = _float("US_PTR_TIMEOUT", 30.0)
US_PTR_RETRIES = _int("US_PTR_RETRIES", 2)
US_PTR_REQUEST_INTERVAL = _float("US_PTR_REQUEST_INTERVAL", 1.0)
US_PTR_MAX_AGE = _int("US_PTR_MAX_AGE", 60 * 60 * 6)

# KRX OPEN API stays off permanently. This is no longer our reading of the
# terms: KRX 데이터사업부 answered the operator on 2026-08-24 and said it in
# their own words — "상업적 목적을 위한 라이선스 계약 등은 존재하지 않습니다",
# and the ban on redistribution "API 상의 수치 데이터를 웹사이트에 그대로
# 표출하는 것도 포함합니다". There is no approval to wait for; the commercial
# path is KOSCOM, a different company and a different price class (§6.2b).
#
# The FSC lane above does not change this: it is a separate grant over a
# separate, next-day dataset, not KRX approval arriving by another route.
# 국내 종목 종가 미리 수집. 사람이 실제로 검색하는 것은 시총 위쪽 몇백 종목이고,
# 그 페이지에 값이 있어야 검색엔진에 올릴 것이 생긴다(2026-08-24 실측: 2,873종목 중
# 값이 있는 것이 19개였다 — 나머지는 방문할 때 그 자리에서 모으는 구조라 크롤러가
# 볼 때는 비어 있다). 한 바퀴에 조금씩만 모아 data.go.kr 일일 한도를 지킨다.
KR_PRECOLLECT_TOP = _int("KR_PRECOLLECT_TOP", 300)
KR_PRECOLLECT_PER_RUN = _int("KR_PRECOLLECT_PER_RUN", 20)

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
