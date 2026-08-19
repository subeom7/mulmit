"""가격·메타데이터 영속 저장소.

요청 경로에서 야후를 부르지 않는 게 목표다. 배치(ingest.py)가 여기에
채워 넣고, 서비스는 여기서만 읽는다. 그래야 야후가 막히든 느리든
사용자 응답과 무관해진다.

SQLAlchemy Core만 쓴다. 로컬은 SQLite, 배포는 Postgres인데 같은 코드가
양쪽에서 돈다. ORM을 안 쓰는 건 모델이 표 네 개뿐이고 대량 upsert가
주 작업이라 Core가 더 단순하고 빠르기 때문이다.

시각은 전부 **epoch 초(float)** 로 저장한다. SQLite에는 타임존 개념이 없어
DateTime을 쓰면 두 DB의 동작이 갈린다. 나이 계산도 뺄셈 한 번이면 끝난다.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import gzip
import json
import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

import pandas as pd
import sqlalchemy as sa

from . import config

log = logging.getLogger(__name__)

metadata = sa.MetaData()

prices = sa.Table(
    "prices",
    metadata,
    sa.Column("ticker", sa.String(32), primary_key=True),
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("close", sa.Float, nullable=False),
)

instruments = sa.Table(
    "instruments",
    metadata,
    sa.Column("ticker", sa.String(32), primary_key=True),
    sa.Column("name", sa.String(256)),
    sa.Column("currency", sa.String(16)),
    sa.Column("exchange", sa.String(32)),
    sa.Column("quote_type", sa.String(32)),
    sa.Column("sector", sa.String(128)),
    sa.Column("industry", sa.String(128)),
    sa.Column("market_cap", sa.Float),
    sa.Column("forward_pe", sa.Float),
    sa.Column("trailing_pe", sa.Float),
    sa.Column("dividend_yield", sa.Float),
    sa.Column("provider_beta", sa.Float),
    sa.Column("first_date", sa.Date),
    sa.Column("last_date", sa.Date),
    sa.Column("prices_updated_at", sa.Float),
    sa.Column("info_updated_at", sa.Float),
    # ok | unavailable. unavailable은 오타난 티커를 기억해 두는 용도라
    # 같은 입력으로 야후를 반복해서 두드리지 않는다.
    sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
    sa.Column("error", sa.Text),
    # 배치가 어떤 티커를 먼저 갱신할지 정하는 기준
    sa.Column("request_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("last_requested_at", sa.Float),
    sa.Index("ix_instruments_refresh", "status", "prices_updated_at"),
)

macro = sa.Table(
    "macro",
    metadata,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.Float, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
)

# FRED 시계열은 ``macro``의 단일 최신값과 분리한다. 관측치를 날짜별로
# 정규화해 두어 카드, 변화율, 장기 차트가 모두 네트워크 없이 같은 원본을 읽는다.
fred_series = sa.Table(
    "fred_series",
    metadata,
    sa.Column("series_id", sa.String(64), primary_key=True),
    sa.Column("title", sa.String(512), nullable=False),
    sa.Column("units", sa.String(256)),
    sa.Column("units_short", sa.String(128)),
    sa.Column("frequency", sa.String(128)),
    sa.Column("frequency_short", sa.String(32)),
    sa.Column("seasonal_adjustment", sa.String(128)),
    sa.Column("seasonal_adjustment_short", sa.String(32)),
    sa.Column("observation_start", sa.Date),
    sa.Column("observation_end", sa.Date),
    sa.Column("provider_last_updated", sa.String(64)),
    sa.Column("notes", sa.Text),
    sa.Column("publisher", sa.String(256)),
    sa.Column("publisher_url", sa.String(512)),
    sa.Column("series_url", sa.String(512), nullable=False),
    sa.Column("copyrighted", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("observation_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("last_observation_date", sa.Date),
    sa.Column("fetched_at", sa.Float),
    sa.Column("last_attempted_at", sa.Float),
    sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
    sa.Column("error", sa.Text),
    sa.Index("ix_fred_series_freshness", "status", "fetched_at"),
)

fred_observations = sa.Table(
    "fred_observations",
    metadata,
    sa.Column("series_id", sa.String(64), primary_key=True),
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("value", sa.Float, nullable=False),
    sa.Index("ix_fred_observations_date", "date"),
)

# 공급자 중립 거시 시계열. 위의 fred_* 테이블을 대체한다.
#
# 이름과 메타데이터가 FRED에 묶여 있으면 NY Fed·BLS·EIA를 직접 연결할 때마다
# 스키마를 다시 손대야 한다. 여기서는 내부 안정 키(series_key)와 공급자 원본
# ID(provider_series_id)를 분리하고, 권리 상태를 행에 함께 저장한다.
#
# 권리 상태를 행에 두는 이유: lane 게이트(app/data_rights.py)는 "이 공급자를
# 서빙해도 되는가"를 답하지만, 같은 공급자 안에서도 계열별로 조건이 다르다.
# FRED의 VIXCLS는 Cboe 권리라 FRED lane이 열려도 값을 내보내면 안 된다.
economic_series = sa.Table(
    "economic_series",
    metadata,
    # 내부 안정 키. 공급자를 바꿔도 카드가 따라오도록 UI key와 같은 문자열을 쓴다.
    sa.Column("series_key", sa.String(64), primary_key=True),
    sa.Column("provider_id", sa.String(32), nullable=False),
    sa.Column("provider_series_id", sa.String(64), nullable=False),
    sa.Column("title", sa.String(512), nullable=False),
    # 공급자가 준 원 단위를 그대로 보관한다. UI가 $B/$T를 추정하지 않게 하려면
    # 여기 값이 유일한 근거여야 한다.
    sa.Column("units", sa.String(256)),
    sa.Column("units_short", sa.String(128)),
    sa.Column("frequency", sa.String(128)),
    sa.Column("frequency_short", sa.String(32)),
    sa.Column("seasonal_adjustment", sa.String(128)),
    sa.Column("seasonal_adjustment_short", sa.String(32)),
    sa.Column("publisher", sa.String(256)),
    sa.Column("publisher_url", sa.String(512)),
    sa.Column("series_url", sa.String(512), nullable=False),
    # approved | pending | license_required | disabled. 기본값은 fail-closed다.
    sa.Column("rights_status", sa.String(24), nullable=False, server_default="pending"),
    sa.Column("rights_evidence", sa.Text),
    sa.Column("notes", sa.Text),
    sa.Column("observation_start", sa.Date),
    sa.Column("observation_end", sa.Date),
    sa.Column("provider_last_updated", sa.String(64)),
    sa.Column("observation_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("last_observation_date", sa.Date),
    sa.Column("fetched_at", sa.Float),
    sa.Column("last_attempted_at", sa.Float),
    sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
    sa.Column("error", sa.Text),
    sa.Index("ix_economic_series_provider", "provider_id", "rights_status"),
    sa.Index("ix_economic_series_freshness", "status", "fetched_at"),
)

economic_observations = sa.Table(
    "economic_observations",
    metadata,
    sa.Column("series_key", sa.String(64), primary_key=True),
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("value", sa.Float, nullable=False),
    sa.Index("ix_economic_observations_date", "date"),
)

# SEC EDGAR 지분공시(Form 3/4/5). 공시는 한 번 제출되면 바뀌지 않고 정정은
# 새 accession으로 올라오므로, 배치는 최근 N건만 받아 upsert하고 이미 받은
# 과거 공시는 그대로 쌓아 둔다.
sec_companies = sa.Table(
    "sec_companies",
    metadata,
    sa.Column("ticker", sa.String(32), primary_key=True),
    sa.Column("cik", sa.String(16)),
    sa.Column("name", sa.String(256)),
    sa.Column("exchange", sa.String(64)),
    sa.Column("filings_seen", sa.Integer, nullable=False, server_default="0"),
    sa.Column("fetched_at", sa.Float),
    sa.Column("last_attempted_at", sa.Float),
    # ok | unavailable | error. unavailable은 EDGAR에 없는 티커를 기억해 둔다.
    sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
    sa.Column("error", sa.Text),
    # 사용자가 검색한 티커를 배치가 우선 수집하게 하는 기준. instruments와 같은 방식.
    sa.Column("request_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("last_requested_at", sa.Float),
    sa.Index("ix_sec_companies_refresh", "status", "fetched_at"),
)

insider_transactions = sa.Table(
    "insider_transactions",
    metadata,
    sa.Column("accession_number", sa.String(32), primary_key=True),
    sa.Column("sequence", sa.Integer, primary_key=True),
    sa.Column("ticker", sa.String(32), nullable=False),
    sa.Column("cik", sa.String(16)),
    sa.Column("form_type", sa.String(8), nullable=False),
    sa.Column("filing_date", sa.Date, nullable=False),
    sa.Column("transaction_date", sa.Date),
    sa.Column("owner_name", sa.String(256), nullable=False),
    sa.Column("owner_cik", sa.String(16)),
    sa.Column("owner_title", sa.String(256)),
    sa.Column("is_director", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("is_officer", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("is_ten_percent_owner", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("security_title", sa.String(256)),
    sa.Column("transaction_code", sa.String(4)),
    sa.Column("acquired_disposed", sa.String(4)),
    sa.Column("is_derivative", sa.Boolean, nullable=False, server_default=sa.false()),
    # 공시에 값이 없는 칸이 흔하다(예: 무상 부여의 단가). 0으로 채우지 않는다.
    sa.Column("shares", sa.Float),
    sa.Column("price_per_share", sa.Float),
    sa.Column("shares_owned_after", sa.Float),
    sa.Column("direct_or_indirect", sa.String(4)),
    sa.Column("filing_url", sa.String(512), nullable=False),
    sa.Index("ix_insider_ticker_date", "ticker", "transaction_date"),
)

# 조립된 응답 캐시. RANDOM_SEED가 고정이라 (티커, 파라미터, 마지막 거래일)이
# 같으면 결과 JSON이 바이트 단위로 같다. 그래서 통째로 캐시해도 안전하다.
# 국내 상장 종목 로스터. 금융위원회 주식시세정보의 하루치 스냅샷(전 종목의
# 코드·이름·시장·종가)을 통째로 갈아끼운다. 이름 검색은 이 테이블만 읽으므로
# 타이핑마다 외부 API를 부르지 않는다.
kr_listings = sa.Table(
    "kr_listings",
    metadata,
    sa.Column("srtn_cd", sa.String(12), primary_key=True),
    sa.Column("itms_nm", sa.String(256), nullable=False),
    sa.Column("mrkt_ctg", sa.String(24), nullable=False),
    sa.Column("isin_cd", sa.String(24)),
    sa.Column("clpr", sa.Float),
    sa.Column("flt_rt", sa.Float),
    sa.Column("mrkt_tot_amt", sa.Float),
    sa.Column("bas_dt", sa.String(10), nullable=False),
    sa.Column("fetched_at", sa.Float, nullable=False),
    sa.Index("ix_kr_listings_name", "itms_nm"),
)

# 국내 지수 하루치 스냅샷. 지수 데이터셋은 하루 한 번의 요청으로 전 지수의
# 종가·전일대비·연초대비·52주 최고/최저·거래량·거래대금을 모두 주므로,
# 지수군 표는 이 테이블만 읽는다.
kr_index_snapshot = sa.Table(
    "kr_index_snapshot",
    metadata,
    # 지수명은 분류를 넘어 유일하지 않다 — "IT 서비스"와 "화학"은 KOSPI와
    # KOSDAQ 시리즈에 같은 이름으로 존재한다. 이름만 키로 쓰면 둘이 충돌한다.
    sa.Column("idx_nm", sa.String(128), primary_key=True),
    sa.Column("idx_csf", sa.String(64), primary_key=True),
    sa.Column("clpr", sa.Float),
    sa.Column("vs", sa.Float),
    sa.Column("flt_rt", sa.Float),
    sa.Column("ls_yr_flt_rt", sa.Float),
    sa.Column("yr_hgst", sa.Float),
    sa.Column("yr_hgst_dt", sa.String(10)),
    sa.Column("yr_lwst", sa.Float),
    sa.Column("yr_lwst_dt", sa.String(10)),
    sa.Column("trqu", sa.Float),
    sa.Column("tr_prc", sa.Float),
    sa.Column("lstg_mrkt_tot_amt", sa.Float),
    sa.Column("bas_dt", sa.String(10), nullable=False),
    sa.Column("fetched_at", sa.Float, nullable=False),
)

# ETF 하루 스냅샷(증권상품시세정보). 종가·NAV·거래대금·기초지수명을 한 행에
# 담으므로, ETF 보드는 이 테이블만 읽고 이력을 수집하지 않는다.
kr_etf_snapshot = sa.Table(
    "kr_etf_snapshot",
    metadata,
    sa.Column("srtn_cd", sa.String(12), primary_key=True),
    sa.Column("itms_nm", sa.String(256), nullable=False),
    sa.Column("clpr", sa.Float),
    sa.Column("vs", sa.Float),
    sa.Column("flt_rt", sa.Float),
    sa.Column("nav", sa.Float),
    sa.Column("trqu", sa.Float),
    sa.Column("tr_prc", sa.Float),
    sa.Column("mrkt_tot_amt", sa.Float),
    sa.Column("n_ppt_tot_amt", sa.Float),
    sa.Column("bss_idx_idx_nm", sa.String(256)),
    sa.Column("bss_idx_clpr", sa.Float),
    sa.Column("bas_dt", sa.String(10), nullable=False),
    sa.Column("fetched_at", sa.Float, nullable=False),
)

# DART 법인코드 매핑. corpCode.xml zip에서 상장사(종목코드 보유)만 담는다.
dart_corp_codes = sa.Table(
    "dart_corp_codes",
    metadata,
    sa.Column("stock_code", sa.String(12), primary_key=True),
    sa.Column("corp_code", sa.String(8), nullable=False),
    sa.Column("corp_name", sa.String(256), nullable=False),
    sa.Column("modify_date", sa.String(10)),
    sa.Column("fetched_at", sa.Float, nullable=False),
)

reports = sa.Table(
    "reports",
    metadata,
    sa.Column("cache_key", sa.String(128), primary_key=True),
    sa.Column("payload", sa.LargeBinary, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Index("ix_reports_created", "created_at"),
)

# 자체 방문 통계. 일×경로×유입호스트 단위 집계와, 일×익명id 고유방문 기록.
pageviews = sa.Table(
    "pageviews",
    metadata,
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("path", sa.String(64), primary_key=True),
    sa.Column("referrer_host", sa.String(128), primary_key=True, server_default=""),
    sa.Column("count", sa.Integer, nullable=False, server_default="0"),
)

visitor_days = sa.Table(
    "visitor_days",
    metadata,
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("client_id", sa.String(64), primary_key=True),
)

# 접속자 하트비트. 브라우저가 만든 익명 무작위 id 하나당 한 행이라 개인정보가
# 없고, 오래된 행은 하트비트가 올 때마다 지워져 테이블이 항상 최근 크기로 남는다.
# 워커가 여럿이라 프로세스 메모리 대신 DB에 둔다.
presence = sa.Table(
    "presence",
    metadata,
    sa.Column("client_id", sa.String(64), primary_key=True),
    sa.Column("seen_at", sa.Float, nullable=False),
    sa.Index("ix_presence_seen", "seen_at"),
)

# 우리 커버리지 내 기업의 8-K 이벤트 공시. 내부자 수집이 이미 받는 submissions
# 응답에서 같이 뽑아 저장한다 — 이 표를 위해 EDGAR를 따로 부르지 않는다.
company_events = sa.Table(
    "company_events",
    metadata,
    sa.Column("accession_number", sa.String(32), primary_key=True),
    sa.Column("ticker", sa.String(32), nullable=False),
    sa.Column("cik", sa.String(16)),
    sa.Column("form_type", sa.String(12), nullable=False),
    sa.Column("filed_at", sa.Date, nullable=False),
    # EDGAR acceptanceDateTime 원문(ISO). 없으면 null — 만들어내지 않는다.
    sa.Column("accepted_at", sa.String(32)),
    sa.Column("items", sa.String(256)),
    sa.Column("url", sa.String(512), nullable=False),
    sa.Index("ix_company_events_filed", "filed_at"),
)

_engine: sa.Engine | None = None
_engine_lock = threading.Lock()


def engine() -> sa.Engine:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            _engine = _build_engine()
    return _engine


def _build_engine() -> sa.Engine:
    url = sa.make_url(config.DATABASE_URL)
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}

    if url.drivername.startswith("sqlite"):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # FastAPI가 동기 엔드포인트를 스레드풀로 넘기므로 커넥션이
        # 생성 스레드 밖에서 쓰인다.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        kwargs.pop("pool_pre_ping")
    else:
        # 유휴 커넥션이 끊기는 환경(로드밸런서/RDS)을 대비해 30분마다 재생성
        kwargs["pool_recycle"] = 1800
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5

    eng = sa.create_engine(url, **kwargs)

    if url.drivername.startswith("sqlite"):
        @sa.event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 드라이버 훅
            cur = dbapi_conn.cursor()
            # WAL이어야 배치가 쓰는 동안 읽기가 안 막힌다
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return eng


def init_db() -> None:
    eng = engine()
    if eng.dialect.name != "postgresql":
        metadata.create_all(eng)
        return

    # web and ingest containers can boot simultaneously. PostgreSQL's
    # check-first CREATE TABLE sequence is not race-free across processes, so
    # serialize this lightweight schema bootstrap until formal migrations are
    # introduced.
    with eng.begin() as conn:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": 556_794_014_902})
        metadata.create_all(conn)


def reset(url: str | None = None) -> None:
    """테스트용. 엔진을 버리고 (선택적으로) 새 URL로 다시 연다."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
    if url is not None:
        config.DATABASE_URL = url


def _upsert(table: sa.Table, rows: list[dict], update_cols: Iterable[str]):
    """SQLite/Postgres 공통 upsert.

    두 방언 모두 ON CONFLICT DO UPDATE를 지원하지만 import 경로가 다르다.
    """
    if engine().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert

    stmt = insert(table).values(rows)
    keys = [c.name for c in table.primary_key.columns]
    return stmt.on_conflict_do_update(
        index_elements=keys,
        set_={col: getattr(stmt.excluded, col) for col in update_cols},
    )


# --- 가격 -------------------------------------------------------------------


def save_prices(ticker: str, close: pd.Series) -> int:
    """종가 시리즈를 저장하고 instruments의 기간·갱신시각을 맞춘다."""
    if close.empty:
        return 0

    rows = [
        {"ticker": ticker, "date": idx.date(), "close": float(val)}
        for idx, val in close.items()
    ]

    with engine().begin() as conn:
        # 대량 insert는 청크로 나눈다. SQLite는 변수 999개 제한이 있고
        # Postgres도 한 문장이 너무 커지면 계획 수립이 느려진다.
        for start in range(0, len(rows), 500):
            conn.execute(_upsert(prices, rows[start : start + 500], ["close"]))

        conn.execute(
            _upsert(
                instruments,
                [{
                    "ticker": ticker,
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "prices_updated_at": time.time(),
                    "status": "ok",
                    "error": None,
                }],
                ["first_date", "last_date", "prices_updated_at", "status", "error"],
            )
        )
    return len(rows)


def load_close(ticker: str) -> pd.Series | None:
    """저장된 종가 시리즈. 없으면 None."""
    stmt = (
        sa.select(prices.c.date, prices.c.close)
        .where(prices.c.ticker == ticker)
        .order_by(prices.c.date)
    )
    with engine().connect() as conn:
        rows = conn.execute(stmt).all()

    if len(rows) < 2:
        return None
    index = pd.DatetimeIndex([r.date for r in rows], name="Date")
    return pd.Series([r.close for r in rows], index=index, dtype="float64")


# --- 종목 메타데이터 ---------------------------------------------------------

_INFO_MAP = {
    "name": ("longName", "shortName"),
    "currency": ("currency",),
    "exchange": ("exchange",),
    "quote_type": ("quoteType",),
    "sector": ("sector",),
    "industry": ("industry",),
    "market_cap": ("marketCap",),
    "forward_pe": ("forwardPE",),
    "trailing_pe": ("trailingPE",),
    "dividend_yield": ("dividendYield",),
    "provider_beta": ("beta",),
}


def save_info(ticker: str, info: dict) -> None:
    row: dict[str, Any] = {"ticker": ticker, "info_updated_at": time.time()}
    for column, candidates in _INFO_MAP.items():
        for key in candidates:
            if info.get(key) is not None:
                row[column] = info[key]
                break
    with engine().begin() as conn:
        conn.execute(_upsert(instruments, [row], [c for c in row if c != "ticker"]))


def get_instrument(ticker: str) -> dict | None:
    stmt = sa.select(instruments).where(instruments.c.ticker == ticker)
    with engine().connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def info_dict(record: dict | None) -> dict:
    """instruments 레코드를 기존 코드가 기대하는 yfinance info 형태로 되돌린다."""
    if not record:
        return {}
    out = {
        "longName": record.get("name"),
        "currency": record.get("currency"),
        "exchange": record.get("exchange"),
        "quoteType": record.get("quote_type"),
        "sector": record.get("sector"),
        "industry": record.get("industry"),
        "marketCap": record.get("market_cap"),
        "forwardPE": record.get("forward_pe"),
        "trailingPE": record.get("trailing_pe"),
        "dividendYield": record.get("dividend_yield"),
        "beta": record.get("provider_beta"),
    }
    return {k: v for k, v in out.items() if v is not None}


def mark_unavailable(ticker: str, message: str) -> None:
    """없는 티커를 기억한다. NEGATIVE_TTL 동안 재조회하지 않는다."""
    with engine().begin() as conn:
        conn.execute(
            _upsert(
                instruments,
                [{
                    "ticker": ticker,
                    "status": "unavailable",
                    "error": message[:500],
                    "prices_updated_at": time.time(),
                }],
                ["status", "error", "prices_updated_at"],
            )
        )


def mark_checked(ticker: str) -> None:
    """확인은 했고 새 데이터가 없었다. status는 건드리지 않는다.

    이게 없으면 휴장일마다 배치가 같은 티커를 매 주기 다시 두드린다.
    """
    with engine().begin() as conn:
        conn.execute(
            sa.update(instruments)
            .where(instruments.c.ticker == ticker)
            .values(prices_updated_at=time.time())
        )


def touch_request(ticker: str) -> None:
    """조회 횟수를 센다. 배치가 인기 티커를 먼저 갱신하는 근거."""
    now = time.time()
    with engine().begin() as conn:
        updated = conn.execute(
            sa.update(instruments)
            .where(instruments.c.ticker == ticker)
            .values(
                request_count=instruments.c.request_count + 1,
                last_requested_at=now,
            )
        ).rowcount
        if not updated:
            conn.execute(
                _upsert(
                    instruments,
                    [{"ticker": ticker, "request_count": 1, "last_requested_at": now}],
                    ["last_requested_at"],
                )
            )


def stale_tickers(max_age: int, limit: int) -> list[str]:
    """갱신이 필요한 티커. 많이 조회된 것부터."""
    cutoff = time.time() - max_age
    stmt = (
        sa.select(instruments.c.ticker)
        .where(
            instruments.c.status == "ok",
            sa.or_(
                instruments.c.prices_updated_at.is_(None),
                instruments.c.prices_updated_at <= cutoff,
            ),
        )
        .order_by(
            instruments.c.request_count.desc(),
            instruments.c.prices_updated_at.asc().nulls_first(),
        )
        .limit(limit)
    )
    with engine().connect() as conn:
        return [r.ticker for r in conn.execute(stmt)]


# --- 거시 지표 ---------------------------------------------------------------


def save_macro(key: str, value: float) -> None:
    with engine().begin() as conn:
        conn.execute(
            _upsert(
                macro,
                [{"key": key, "value": float(value), "updated_at": time.time()}],
                ["value", "updated_at"],
            )
        )


def load_macro(key: str, max_age: int | None = None) -> float | None:
    stmt = sa.select(macro.c.value, macro.c.updated_at).where(macro.c.key == key)
    with engine().connect() as conn:
        row = conn.execute(stmt).first()
    if row is None:
        return None
    # `>=`인 이유: 시계 해상도 안에서 저장과 조회가 같은 눈금에 떨어지면 나이가
    # 정확히 0.0이 된다. `>`면 max_age=0이 "항상 만료"를 뜻하지 못하고 값을 그대로
    # 돌려준다. Windows에서는 이 충돌이 드물지 않다.
    if max_age is not None and time.time() - row.updated_at >= max_age:
        return None
    return float(row.value)


# --- FRED 정규화 시계열 ------------------------------------------------------


def _optional_date(value: Any) -> Any:
    if value in {None, ""} or isinstance(value, dt.date):
        return value or None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def save_fred_series(
    series_id: str,
    remote_metadata: dict[str, Any],
    observations: Iterable[tuple[dt.date, float]],
    *,
    publisher: str,
    publisher_url: str,
    series_url: str,
) -> int:
    """Replace one FRED series atomically with its current-vintage observations."""
    series_id = series_id.strip().upper()
    values = sorted({date: float(value) for date, value in observations}.items())
    if not values:
        raise ValueError(f"{series_id} observations must not be empty")

    now = time.time()
    notes = str(remote_metadata.get("notes") or "")
    row = {
        "series_id": series_id,
        "title": str(remote_metadata.get("title") or series_id),
        "units": remote_metadata.get("units"),
        "units_short": remote_metadata.get("units_short"),
        "frequency": remote_metadata.get("frequency"),
        "frequency_short": remote_metadata.get("frequency_short"),
        "seasonal_adjustment": remote_metadata.get("seasonal_adjustment"),
        "seasonal_adjustment_short": remote_metadata.get("seasonal_adjustment_short"),
        "observation_start": _optional_date(remote_metadata.get("observation_start")),
        "observation_end": _optional_date(remote_metadata.get("observation_end")),
        "provider_last_updated": remote_metadata.get("last_updated"),
        "notes": notes,
        "publisher": publisher,
        "publisher_url": publisher_url,
        "series_url": series_url,
        "copyrighted": "copyright" in notes.lower(),
        "observation_count": len(values),
        "last_observation_date": values[-1][0],
        "fetched_at": now,
        "last_attempted_at": now,
        "status": "ok",
        "error": None,
    }
    observation_rows = [
        {"series_id": series_id, "date": date, "value": value}
        for date, value in values
    ]

    with engine().begin() as conn:
        existing_values = [
            (item.date, float(item.value))
            for item in conn.execute(
                sa.select(fred_observations.c.date, fred_observations.c.value)
                .where(fred_observations.c.series_id == series_id)
                .order_by(fred_observations.c.date)
            )
        ]
        conn.execute(_upsert(fred_series, [row], [key for key in row if key != "series_id"]))
        if existing_values == values:
            return len(values)
        # 전체 현재 빈티지를 받으므로 교정되거나 제거된 과거 관측치까지 정확히 반영한다.
        conn.execute(
            sa.delete(fred_observations).where(fred_observations.c.series_id == series_id)
        )
        for start in range(0, len(observation_rows), 1000):
            conn.execute(sa.insert(fred_observations), observation_rows[start : start + 1000])
    return len(values)


def mark_fred_error(series_id: str, message: str) -> None:
    """Record an ingest error without discarding the last known-good observations."""
    series_id = series_id.strip().upper()
    now = time.time()
    with engine().begin() as conn:
        existing = conn.execute(
            sa.select(fred_series.c.series_id).where(fred_series.c.series_id == series_id)
        ).first()
        if existing:
            conn.execute(
                sa.update(fred_series)
                .where(fred_series.c.series_id == series_id)
                .values(status="error", error=message[:1000], last_attempted_at=now)
            )
        else:
            conn.execute(
                sa.insert(fred_series).values(
                    series_id=series_id,
                    title=series_id,
                    series_url=f"https://fred.stlouisfed.org/series/{series_id}",
                    status="error",
                    error=message[:1000],
                    last_attempted_at=now,
                )
            )


def get_fred_series(series_id: str) -> dict | None:
    stmt = sa.select(fred_series).where(
        fred_series.c.series_id == series_id.strip().upper()
    )
    with engine().connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def list_fred_series(series_ids: Iterable[str] | None = None) -> list[dict]:
    stmt = sa.select(fred_series)
    if series_ids is not None:
        normalized = [series_id.strip().upper() for series_id in series_ids]
        if not normalized:
            return []
        stmt = stmt.where(fred_series.c.series_id.in_(normalized))
    stmt = stmt.order_by(fred_series.c.series_id)
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def stale_fred_series(series_ids: Iterable[str], max_age: int) -> list[str]:
    """Return catalog ids missing a successful fetch or older than ``max_age``."""
    ordered = list(dict.fromkeys(series_id.strip().upper() for series_id in series_ids))
    if not ordered:
        return []
    cutoff = time.time() - max_age
    stmt = sa.select(
        fred_series.c.series_id,
        fred_series.c.fetched_at,
        fred_series.c.status,
    ).where(fred_series.c.series_id.in_(ordered))
    with engine().connect() as conn:
        fetched = {
            row.series_id: (row.fetched_at, row.status) for row in conn.execute(stmt)
        }
    return [
        series_id
        for series_id in ordered
        if series_id not in fetched
        or fetched[series_id][0] is None
        or fetched[series_id][0] <= cutoff
        or fetched[series_id][1] != "ok"
    ]


def load_fred_observations(
    series_id: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list[tuple[dt.date, float]]:
    stmt = sa.select(fred_observations.c.date, fred_observations.c.value).where(
        fred_observations.c.series_id == series_id.strip().upper()
    )
    if start is not None:
        stmt = stmt.where(fred_observations.c.date >= start)
    if end is not None:
        stmt = stmt.where(fred_observations.c.date <= end)
    stmt = stmt.order_by(fred_observations.c.date)
    with engine().connect() as conn:
        return [(row.date, float(row.value)) for row in conn.execute(stmt)]


# --- 공급자 중립 거시 시계열 -------------------------------------------------


def save_economic_series(
    series_key: str,
    *,
    provider_id: str,
    provider_series_id: str,
    metadata_fields: dict[str, Any],
    observations: Iterable[tuple[dt.date, float]],
    publisher: str,
    publisher_url: str,
    series_url: str,
    rights_status: str = "pending",
    rights_evidence: str | None = None,
) -> int:
    """Replace one series atomically with its current vintage.

    Providers that hand back the whole series each time (FRED, NY Fed CSV) can
    revise or withdraw past observations, so a replace is the only way to stay
    faithful to the current vintage. The swap only happens when the values
    actually differ, which keeps a no-op refresh from rewriting the table.
    """
    series_key = series_key.strip()
    if not series_key:
        raise ValueError("series_key must not be empty")
    values = sorted({date: float(value) for date, value in observations}.items())
    if not values:
        raise ValueError(f"{series_key} observations must not be empty")

    now = time.time()
    row = {
        "series_key": series_key,
        "provider_id": provider_id,
        "provider_series_id": provider_series_id,
        "title": str(metadata_fields.get("title") or provider_series_id),
        "units": metadata_fields.get("units"),
        "units_short": metadata_fields.get("units_short"),
        "frequency": metadata_fields.get("frequency"),
        "frequency_short": metadata_fields.get("frequency_short"),
        "seasonal_adjustment": metadata_fields.get("seasonal_adjustment"),
        "seasonal_adjustment_short": metadata_fields.get("seasonal_adjustment_short"),
        "publisher": publisher,
        "publisher_url": publisher_url,
        "series_url": series_url,
        "rights_status": rights_status,
        "rights_evidence": rights_evidence,
        "notes": str(metadata_fields.get("notes") or ""),
        "observation_start": _optional_date(metadata_fields.get("observation_start")),
        "observation_end": _optional_date(metadata_fields.get("observation_end")),
        "provider_last_updated": metadata_fields.get("last_updated"),
        "observation_count": len(values),
        "last_observation_date": values[-1][0],
        "fetched_at": now,
        "last_attempted_at": now,
        "status": "ok",
        "error": None,
    }
    observation_rows = [
        {"series_key": series_key, "date": date, "value": value} for date, value in values
    ]

    with engine().begin() as conn:
        existing = [
            (item.date, float(item.value))
            for item in conn.execute(
                sa.select(economic_observations.c.date, economic_observations.c.value)
                .where(economic_observations.c.series_key == series_key)
                .order_by(economic_observations.c.date)
            )
        ]
        conn.execute(
            _upsert(economic_series, [row], [key for key in row if key != "series_key"])
        )
        if existing == values:
            return len(values)
        conn.execute(
            sa.delete(economic_observations).where(
                economic_observations.c.series_key == series_key
            )
        )
        for start in range(0, len(observation_rows), 1000):
            conn.execute(
                sa.insert(economic_observations), observation_rows[start : start + 1000]
            )
    return len(values)


def mark_economic_error(series_key: str, message: str) -> None:
    """Record a failure without discarding the last known-good observations."""
    series_key = series_key.strip()
    now = time.time()
    with engine().begin() as conn:
        updated = conn.execute(
            sa.update(economic_series)
            .where(economic_series.c.series_key == series_key)
            .values(status="error", error=message[:1000], last_attempted_at=now)
        ).rowcount
        if not updated:
            log.warning("알 수 없는 시계열의 오류를 기록하지 않는다: %s", series_key)


def get_economic_series(series_key: str) -> dict | None:
    stmt = sa.select(economic_series).where(economic_series.c.series_key == series_key.strip())
    with engine().connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def list_economic_series(
    series_keys: Iterable[str] | None = None,
    *,
    provider_id: str | None = None,
) -> list[dict]:
    stmt = sa.select(economic_series)
    if series_keys is not None:
        keys = [key.strip() for key in series_keys]
        if not keys:
            return []
        stmt = stmt.where(economic_series.c.series_key.in_(keys))
    if provider_id is not None:
        stmt = stmt.where(economic_series.c.provider_id == provider_id)
    stmt = stmt.order_by(economic_series.c.series_key)
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def load_economic_observations(
    series_key: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list[tuple[dt.date, float]]:
    stmt = sa.select(economic_observations.c.date, economic_observations.c.value).where(
        economic_observations.c.series_key == series_key.strip()
    )
    if start is not None:
        stmt = stmt.where(economic_observations.c.date >= start)
    if end is not None:
        stmt = stmt.where(economic_observations.c.date <= end)
    stmt = stmt.order_by(economic_observations.c.date)
    with engine().connect() as conn:
        return [(row.date, float(row.value)) for row in conn.execute(stmt)]


def stale_economic_series(series_keys: Iterable[str], max_age: int) -> list[str]:
    """Keys never fetched successfully, or at least ``max_age`` old.

    The cutoff comparison is `<=` for the same reason the cache TTLs are: on a
    coarse clock a row written and checked inside one tick has an age of
    exactly zero, so `<` would make ``max_age=0`` mean "never refresh" instead
    of "always refresh".
    """
    ordered = list(dict.fromkeys(key.strip() for key in series_keys))
    if not ordered:
        return []
    cutoff = time.time() - max_age
    stmt = sa.select(
        economic_series.c.series_key,
        economic_series.c.fetched_at,
        economic_series.c.status,
    ).where(economic_series.c.series_key.in_(ordered))
    with engine().connect() as conn:
        fetched = {row.series_key: (row.fetched_at, row.status) for row in conn.execute(stmt)}
    return [
        key
        for key in ordered
        if key not in fetched
        or fetched[key][0] is None
        or fetched[key][0] <= cutoff
        or fetched[key][1] != "ok"
    ]


def save_kr_listings(rows: Iterable[dict[str, Any]], bas_dt: str) -> int:
    """Replace the whole Korean listing roster with one trading day's snapshot.

    A replace rather than an upsert: delistings must disappear from search, and
    the snapshot is small enough (~3k rows) that atomicity is worth more than
    the delta.
    """
    now = time.time()
    payload = [
        {
            "srtn_cd": str(row["srtn_cd"]).strip(),
            "itms_nm": str(row["itms_nm"]).strip(),
            "mrkt_ctg": str(row.get("mrkt_ctg") or "").strip(),
            "isin_cd": str(row.get("isin_cd") or "").strip() or None,
            "clpr": row.get("clpr"),
            "flt_rt": row.get("flt_rt"),
            "mrkt_tot_amt": row.get("mrkt_tot_amt"),
            "bas_dt": bas_dt,
            "fetched_at": now,
        }
        for row in rows
        if str(row.get("srtn_cd") or "").strip() and str(row.get("itms_nm") or "").strip()
    ]
    if not payload:
        return 0
    with engine().begin() as conn:
        conn.execute(kr_listings.delete())
        conn.execute(kr_listings.insert(), payload)
    return len(payload)


def search_kr_listings(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Name or code search over the local roster, biggest companies first.

    A name-prefix match outranks a substring match so 삼성전자 beats 호텔삼성
    for the query 삼성, and the exact code always wins.
    """
    term = query.strip()
    if not term:
        return []
    like = f"%{term}%"
    prefix = f"{term}%"
    rank = sa.case(
        (kr_listings.c.srtn_cd == term.upper(), 0),
        (kr_listings.c.itms_nm == term, 1),
        (kr_listings.c.itms_nm.like(prefix), 2),
        else_=3,
    )
    stmt = (
        sa.select(kr_listings)
        .where(sa.or_(kr_listings.c.itms_nm.like(like), kr_listings.c.srtn_cd.like(prefix.upper())))
        .order_by(rank, sa.desc(sa.func.coalesce(kr_listings.c.mrkt_tot_amt, 0.0)))
        .limit(max(1, min(int(limit), 25)))
    )
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def get_kr_listing(code: str) -> dict[str, Any] | None:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(kr_listings).where(kr_listings.c.srtn_cd == code.strip().upper())
        ).mappings().first()
        return dict(row) if row else None


def kr_listings_meta() -> dict[str, Any]:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(
                sa.func.count(kr_listings.c.srtn_cd),
                sa.func.max(kr_listings.c.bas_dt),
                sa.func.max(kr_listings.c.fetched_at),
            )
        ).first()
    count, bas_dt, fetched_at = row or (0, None, None)
    return {"count": int(count or 0), "bas_dt": bas_dt, "fetched_at": fetched_at}


def kr_listings_stale(max_age: int) -> bool:
    meta = kr_listings_meta()
    if not meta["count"] or meta["fetched_at"] is None:
        return True
    return meta["fetched_at"] <= time.time() - max_age


def save_kr_index_snapshot(rows: Iterable[dict[str, Any]], bas_dt: str) -> int:
    """Replace the whole index snapshot with one trading day's rows."""
    now = time.time()
    payload = [
        {**row, "bas_dt": bas_dt, "fetched_at": now}
        for row in rows
        if str(row.get("idx_nm") or "").strip()
    ]
    if not payload:
        return 0
    with engine().begin() as conn:
        conn.execute(kr_index_snapshot.delete())
        conn.execute(kr_index_snapshot.insert(), payload)
    return len(payload)


def load_kr_index_snapshot(
    names: Iterable[str] | None = None, *, idx_csf: str | None = None
) -> list[dict[str, Any]]:
    stmt = sa.select(kr_index_snapshot)
    wanted = [str(n).strip() for n in names] if names is not None else None
    if wanted:
        stmt = stmt.where(kr_index_snapshot.c.idx_nm.in_(wanted))
    if idx_csf:
        stmt = stmt.where(kr_index_snapshot.c.idx_csf == idx_csf)
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def kr_index_snapshot_meta() -> dict[str, Any]:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(
                sa.func.count(kr_index_snapshot.c.idx_nm),
                sa.func.max(kr_index_snapshot.c.bas_dt),
                sa.func.max(kr_index_snapshot.c.fetched_at),
            )
        ).first()
    count, bas_dt, fetched_at = row or (0, None, None)
    return {"count": int(count or 0), "bas_dt": bas_dt, "fetched_at": fetched_at}


def kr_index_snapshot_stale(max_age: int) -> bool:
    meta = kr_index_snapshot_meta()
    if not meta["count"] or meta["fetched_at"] is None:
        return True
    return meta["fetched_at"] <= time.time() - max_age


def save_kr_etf_snapshot(rows: Iterable[dict[str, Any]], bas_dt: str) -> int:
    """Replace the whole ETF snapshot with one trading day's rows."""
    now = time.time()
    payload = [
        {**row, "bas_dt": bas_dt, "fetched_at": now}
        for row in rows
        if str(row.get("srtn_cd") or "").strip()
    ]
    if not payload:
        return 0
    with engine().begin() as conn:
        conn.execute(kr_etf_snapshot.delete())
        conn.execute(kr_etf_snapshot.insert(), payload)
    return len(payload)


def load_kr_etf_snapshot() -> list[dict[str, Any]]:
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(sa.select(kr_etf_snapshot)).mappings()]


def kr_etf_snapshot_meta() -> dict[str, Any]:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(
                sa.func.count(kr_etf_snapshot.c.srtn_cd),
                sa.func.max(kr_etf_snapshot.c.bas_dt),
                sa.func.max(kr_etf_snapshot.c.fetched_at),
            )
        ).first()
    count, bas_dt, fetched_at = row or (0, None, None)
    return {"count": int(count or 0), "bas_dt": bas_dt, "fetched_at": fetched_at}


def kr_etf_snapshot_stale(max_age: int) -> bool:
    meta = kr_etf_snapshot_meta()
    if not meta["count"] or meta["fetched_at"] is None:
        return True
    return meta["fetched_at"] <= time.time() - max_age


def save_dart_corp_codes(rows: Iterable[dict[str, Any]]) -> int:
    """Replace the listed-company corp-code mapping wholesale."""
    now = time.time()
    payload = [
        {
            "stock_code": str(row["stock_code"]).strip(),
            "corp_code": str(row["corp_code"]).strip(),
            "corp_name": str(row["corp_name"]).strip(),
            "modify_date": str(row.get("modify_date") or "").strip() or None,
            "fetched_at": now,
        }
        for row in rows
        if str(row.get("stock_code") or "").strip() and str(row.get("corp_code") or "").strip()
    ]
    if not payload:
        return 0
    with engine().begin() as conn:
        conn.execute(dart_corp_codes.delete())
        conn.execute(dart_corp_codes.insert(), payload)
    return len(payload)


def get_dart_corp_code(stock_code: str) -> dict[str, Any] | None:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(dart_corp_codes).where(
                dart_corp_codes.c.stock_code == stock_code.strip().upper()
            )
        ).mappings().first()
        return dict(row) if row else None


def dart_corp_codes_meta() -> dict[str, Any]:
    with engine().connect() as conn:
        row = conn.execute(
            sa.select(
                sa.func.count(dart_corp_codes.c.stock_code),
                sa.func.max(dart_corp_codes.c.fetched_at),
            )
        ).first()
    count, fetched_at = row or (0, None)
    return {"count": int(count or 0), "fetched_at": fetched_at}


def dart_corp_codes_stale(max_age: int) -> bool:
    meta = dart_corp_codes_meta()
    if not meta["count"] or meta["fetched_at"] is None:
        return True
    return meta["fetched_at"] <= time.time() - max_age


def migrate_fred_series_to_economic(
    mapping: Iterable[tuple[str, str, str, str]],
) -> dict[str, int]:
    """Copy legacy ``fred_*`` rows into the neutral tables.

    ``mapping`` yields ``(series_id, series_key, provider_id, rights_status)``.
    Explicit rather than automatic on boot: a migration that runs itself during
    a deploy is one nobody reviews, and the production database currently holds
    no FRED rows at all. The legacy tables are left untouched so this can be
    re-run or abandoned.
    """
    moved = {"series": 0, "observations": 0, "skipped": 0}
    for series_id, series_key, provider_id, rights_status in mapping:
        record = get_fred_series(series_id)
        if record is None:
            moved["skipped"] += 1
            continue
        observations = load_fred_observations(series_id)
        if not observations:
            moved["skipped"] += 1
            continue
        count = save_economic_series(
            series_key,
            provider_id=provider_id,
            provider_series_id=series_id,
            metadata_fields={
                "title": record.get("title"),
                "units": record.get("units"),
                "units_short": record.get("units_short"),
                "frequency": record.get("frequency"),
                "frequency_short": record.get("frequency_short"),
                "seasonal_adjustment": record.get("seasonal_adjustment"),
                "seasonal_adjustment_short": record.get("seasonal_adjustment_short"),
                "observation_start": record.get("observation_start"),
                "observation_end": record.get("observation_end"),
                "last_updated": record.get("provider_last_updated"),
                "notes": record.get("notes"),
            },
            observations=observations,
            publisher=record.get("publisher") or "",
            publisher_url=record.get("publisher_url") or "",
            series_url=record.get("series_url") or "",
            rights_status=rights_status,
            rights_evidence="migrated from legacy fred_series",
        )
        moved["series"] += 1
        moved["observations"] += count
    return moved


# --- SEC EDGAR 지분공시 ------------------------------------------------------


def save_insider_filings(
    ticker: str,
    *,
    cik: str,
    name: str,
    exchange: str | None,
    filings_seen: int,
    transactions: Iterable[dict[str, Any]],
) -> int:
    """Upsert one company's filings.

    Filings are immutable once submitted — a correction arrives as a new
    accession — so rows already collected are kept rather than replaced. That
    lets a small per-cycle fetch limit accumulate real history over time.
    """
    ticker = ticker.strip().upper()
    now = time.time()
    rows = [{**row, "ticker": ticker, "cik": cik} for row in transactions]

    with engine().begin() as conn:
        conn.execute(
            _upsert(
                sec_companies,
                [{
                    "ticker": ticker,
                    "cik": cik,
                    "name": name,
                    "exchange": exchange,
                    "filings_seen": filings_seen,
                    "fetched_at": now,
                    "last_attempted_at": now,
                    "status": "ok",
                    "error": None,
                }],
                ["cik", "name", "exchange", "filings_seen", "fetched_at",
                 "last_attempted_at", "status", "error"],
            )
        )
        for start in range(0, len(rows), 500):
            chunk = rows[start : start + 500]
            conn.execute(
                _upsert(
                    insider_transactions,
                    chunk,
                    [key for key in chunk[0] if key not in {"accession_number", "sequence"}],
                )
            )
    return len(rows)


def mark_insider_error(ticker: str, message: str, *, status: str = "error") -> None:
    """Remember a failure without discarding filings already collected."""
    ticker = ticker.strip().upper()
    now = time.time()
    with engine().begin() as conn:
        updated = conn.execute(
            sa.update(sec_companies)
            .where(sec_companies.c.ticker == ticker)
            .values(status=status, error=message[:1000], last_attempted_at=now)
        ).rowcount
        if not updated:
            conn.execute(
                sa.insert(sec_companies).values(
                    ticker=ticker,
                    status=status,
                    error=message[:1000],
                    last_attempted_at=now,
                )
            )


def get_insider_company(ticker: str) -> dict | None:
    stmt = sa.select(sec_companies).where(sec_companies.c.ticker == ticker.strip().upper())
    with engine().connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def touch_insider_request(ticker: str) -> None:
    """Record that a visitor asked for this ticker so the batch collects it next.

    Request handlers must never call EDGAR, so an unseen ticker is queued here
    and answered on a later visit instead of being fetched inline.
    """
    ticker = ticker.strip().upper()
    now = time.time()
    with engine().begin() as conn:
        updated = conn.execute(
            sa.update(sec_companies)
            .where(sec_companies.c.ticker == ticker)
            .values(
                request_count=sec_companies.c.request_count + 1,
                last_requested_at=now,
            )
        ).rowcount
        if not updated:
            conn.execute(
                sa.insert(sec_companies).values(
                    ticker=ticker,
                    status="queued",
                    request_count=1,
                    last_requested_at=now,
                )
            )


def load_insider_transactions(ticker: str, *, limit: int = 100) -> list[dict]:
    """Most recent reported lines first. Filing date breaks ties for same-day rows."""
    stmt = (
        sa.select(insider_transactions)
        .where(insider_transactions.c.ticker == ticker.strip().upper())
        .order_by(
            insider_transactions.c.transaction_date.desc().nulls_last(),
            insider_transactions.c.filing_date.desc(),
            insider_transactions.c.accession_number.desc(),
            insider_transactions.c.sequence.asc(),
        )
        .limit(limit)
    )
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def stale_insider_tickers(pinned: Iterable[str], max_age: int, limit: int) -> list[str]:
    """Pinned watchlist first, then whatever visitors actually searched for."""
    cutoff = time.time() - max_age
    ordered: list[str] = []
    known = {
        row["ticker"]: row
        for row in (
            dict(item)
            for item in _select_companies()
        )
    }
    for ticker in (t.strip().upper() for t in pinned):
        record = known.get(ticker)
        if ticker in ordered:
            continue
        if record is None or record["status"] == "queued" or (
            record["status"] == "ok" and (record["fetched_at"] or 0) <= cutoff
        ):
            ordered.append(ticker)

    requested = sorted(
        (
            row
            for row in known.values()
            if row["ticker"] not in ordered
            and row["status"] != "unavailable"
            and ((row["fetched_at"] or 0) <= cutoff)
        ),
        key=lambda row: (-(row["request_count"] or 0), row["fetched_at"] or 0.0),
    )
    ordered.extend(row["ticker"] for row in requested)
    return ordered[:limit]


def _select_companies() -> list[dict]:
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(sa.select(sec_companies)).mappings()]


def list_insider_companies(status: str = "ok") -> list[dict]:
    """수집이 끝나 CIK가 붙은 회사들. 재무 배치가 같은 티커 집합을 탄다."""
    stmt = sa.select(sec_companies).where(
        sec_companies.c.status == status, sec_companies.c.cik.is_not(None)
    )
    with engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


# --- 응답 캐시 ---------------------------------------------------------------


def load_report(cache_key: str, ttl: int) -> dict | None:
    stmt = sa.select(reports.c.payload, reports.c.created_at).where(
        reports.c.cache_key == cache_key
    )
    with engine().connect() as conn:
        row = conn.execute(stmt).first()
    # load_macro와 같은 이유로 `>=`. ttl=0은 "캐시를 쓰지 않는다"여야 한다.
    if row is None or time.time() - row.created_at >= ttl:
        return None
    try:
        return json.loads(gzip.decompress(row.payload))
    except Exception:  # 캐시가 깨졌으면 없는 셈 친다
        log.warning("리포트 캐시 복원 실패: %s", cache_key, exc_info=True)
        return None


def save_report(cache_key: str, payload: dict) -> None:
    blob = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 6)
    try:
        with engine().begin() as conn:
            conn.execute(
                _upsert(
                    reports,
                    [{"cache_key": cache_key, "payload": blob, "created_at": time.time()}],
                    ["payload", "created_at"],
                )
            )
    except Exception:  # 캐시 저장 실패로 응답을 막을 이유는 없다
        log.warning("리포트 캐시 저장 실패: %s", cache_key, exc_info=True)


def purge_reports(older_than: int) -> int:
    with engine().begin() as conn:
        return conn.execute(
            sa.delete(reports).where(reports.c.created_at < time.time() - older_than)
        ).rowcount


def stats() -> dict:
    """헬스체크·운영용 요약."""
    with engine().connect() as conn:
        return {
            "instruments": conn.execute(
                sa.select(sa.func.count()).select_from(instruments)
            ).scalar_one(),
            "price_rows": conn.execute(
                sa.select(sa.func.count()).select_from(prices)
            ).scalar_one(),
            "cached_reports": conn.execute(
                sa.select(sa.func.count()).select_from(reports)
            ).scalar_one(),
            "fred_series": conn.execute(
                sa.select(sa.func.count()).select_from(fred_series)
            ).scalar_one(),
            "fred_observations": conn.execute(
                sa.select(sa.func.count()).select_from(fred_observations)
            ).scalar_one(),
            "last_fred_ingest": conn.execute(
                sa.select(sa.func.max(fred_series.c.fetched_at))
            ).scalar(),
            "economic_series": conn.execute(
                sa.select(sa.func.count()).select_from(economic_series)
            ).scalar_one(),
            "economic_observations": conn.execute(
                sa.select(sa.func.count()).select_from(economic_observations)
            ).scalar_one(),
            "last_economic_ingest": conn.execute(
                sa.select(sa.func.max(economic_series.c.fetched_at))
            ).scalar(),
            "insider_companies": conn.execute(
                sa.select(sa.func.count()).select_from(sec_companies)
            ).scalar_one(),
            "insider_transactions": conn.execute(
                sa.select(sa.func.count()).select_from(insider_transactions)
            ).scalar_one(),
            "last_insider_ingest": conn.execute(
                sa.select(sa.func.max(sec_companies.c.fetched_at))
            ).scalar(),
            "last_ingest": conn.execute(
                sa.select(sa.func.max(instruments.c.prices_updated_at))
            ).scalar(),
        }


def touch_presence(
    client_id: str, *, now: float | None = None, window_seconds: float = 90.0
) -> int:
    """하트비트를 기록하고, 창 안에서 살아 있는 브라우저 수를 돌려준다.

    같은 id는 30초마다 한 번 오므로 update가 거의 항상 이긴다. 새 id의 insert가
    다른 워커와 부딪히는 창은 이론상뿐이지만, 부딪혀도 카운트만 반환하면 된다.
    """
    moment = float(now if now is not None else time.time())
    with engine().begin() as conn:
        updated = conn.execute(
            presence.update().where(presence.c.client_id == client_id).values(seen_at=moment)
        ).rowcount
        if not updated:
            with contextlib.suppress(sa.exc.IntegrityError):
                conn.execute(presence.insert().values(client_id=client_id, seen_at=moment))
        # 오래된 행은 하트비트마다 정리한다 — 테이블은 항상 최근 방문자 크기다.
        conn.execute(presence.delete().where(presence.c.seen_at < moment - 3600.0))
        count = conn.execute(
            sa.select(sa.func.count())
            .select_from(presence)
            .where(presence.c.seen_at >= moment - window_seconds)
        ).scalar_one()
    return int(count)


def save_company_events(ticker: str, rows: list[dict]) -> int:
    """한 회사의 8-K 이벤트 행을 upsert한다. accession이 자연 키다."""
    saved = 0
    normalized = str(ticker or "").strip().upper()
    if not normalized:
        return 0
    with engine().begin() as conn:
        for row in rows:
            accession = str(row.get("accession_number") or "").strip()
            if not accession or row.get("filed_at") is None:
                continue
            values = {
                "ticker": normalized,
                "cik": row.get("cik"),
                "form_type": str(row.get("form_type") or "8-K"),
                "filed_at": row["filed_at"],
                "accepted_at": row.get("accepted_at"),
                "items": row.get("items"),
                "url": str(row.get("url") or ""),
            }
            updated = conn.execute(
                company_events.update()
                .where(company_events.c.accession_number == accession)
                .values(**values)
            ).rowcount
            if not updated:
                conn.execute(
                    company_events.insert().values(accession_number=accession, **values)
                )
            saved += 1
    return saved


def load_recent_events(limit: int = 40) -> list[dict]:
    """커버리지 전체에서 최근 8-K를 최신순으로. 회사 이름은 sec_companies에서 조인."""
    with engine().begin() as conn:
        rows = conn.execute(
            sa.select(
                company_events,
                sec_companies.c.name.label("company_name"),
            )
            .join(
                sec_companies,
                company_events.c.ticker == sec_companies.c.ticker,
                isouter=True,
            )
            .order_by(
                company_events.c.filed_at.desc(),
                company_events.c.accepted_at.desc().nulls_last(),
            )
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows]


# --- 방문 통계 (자체 집계) ----------------------------------------------------
# 개인정보 없음: 경로는 닫힌 목록으로 버킷팅, 유입경로는 호스트명만, 방문자
# 구분은 presence와 같은 익명 무작위 id다. 일 단위 집계라 행 수가 작게 유지된다.

def record_pageview(
    path: str,
    referrer_host: str,
    client_id: str,
    *,
    today: dt.date | None = None,
) -> None:
    date = today or dt.date.today()
    host = (referrer_host or "")[:128]
    with engine().begin() as conn:
        updated = conn.execute(
            pageviews.update()
            .where(
                (pageviews.c.date == date)
                & (pageviews.c.path == path)
                & (pageviews.c.referrer_host == host)
            )
            .values(count=pageviews.c.count + 1)
        ).rowcount
        if not updated:
            with contextlib.suppress(sa.exc.IntegrityError):
                conn.execute(
                    pageviews.insert().values(
                        date=date, path=path, referrer_host=host, count=1
                    )
                )
        if client_id:
            with contextlib.suppress(sa.exc.IntegrityError):
                conn.execute(
                    visitor_days.insert().values(date=date, client_id=client_id[:64])
                )


def traffic_stats(days: int = 14, *, today: dt.date | None = None) -> dict:
    """최근 N일 요약: 일별 방문자·조회수, 경로별 합, 상위 유입경로."""
    end = today or dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    with engine().begin() as conn:
        daily_views = dict(conn.execute(
            sa.select(pageviews.c.date, sa.func.sum(pageviews.c.count))
            .where(pageviews.c.date >= start)
            .group_by(pageviews.c.date)
        ).all())
        daily_uniques = dict(conn.execute(
            sa.select(visitor_days.c.date, sa.func.count())
            .where(visitor_days.c.date >= start)
            .group_by(visitor_days.c.date)
        ).all())
        by_path = conn.execute(
            sa.select(pageviews.c.path, sa.func.sum(pageviews.c.count))
            .where(pageviews.c.date >= start)
            .group_by(pageviews.c.path)
            .order_by(sa.func.sum(pageviews.c.count).desc())
        ).all()
        referrers = conn.execute(
            sa.select(pageviews.c.referrer_host, sa.func.sum(pageviews.c.count))
            .where((pageviews.c.date >= start) & (pageviews.c.referrer_host != ""))
            .group_by(pageviews.c.referrer_host)
            .order_by(sa.func.sum(pageviews.c.count).desc())
            .limit(10)
        ).all()
    series = []
    for offset in range(days):
        date = start + dt.timedelta(days=offset)
        series.append({
            "date": date.isoformat(),
            "pageviews": int(daily_views.get(date, 0)),
            "unique_visitors": int(daily_uniques.get(date, 0)),
        })
    return {
        "window_days": days,
        "daily": series,
        "by_path": [{"path": p, "count": int(c)} for p, c in by_path],
        "top_referrers": [{"host": h, "count": int(c)} for h, c in referrers],
    }


def list_kr_codes() -> list[tuple[str, str]]:
    """전 상장 종목의 (코드, 이름) — 종목 허브 사이트맵용."""
    with engine().begin() as conn:
        rows = conn.execute(
            sa.select(kr_listings.c.srtn_cd, kr_listings.c.itms_nm)
            .order_by(kr_listings.c.srtn_cd)
        ).all()
    return [(str(code), str(name or "")) for code, name in rows]
