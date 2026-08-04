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

# 조립된 응답 캐시. RANDOM_SEED가 고정이라 (티커, 파라미터, 마지막 거래일)이
# 같으면 결과 JSON이 바이트 단위로 같다. 그래서 통째로 캐시해도 안전하다.
reports = sa.Table(
    "reports",
    metadata,
    sa.Column("cache_key", sa.String(128), primary_key=True),
    sa.Column("payload", sa.LargeBinary, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Index("ix_reports_created", "created_at"),
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
    metadata.create_all(engine())


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
                instruments.c.prices_updated_at < cutoff,
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
    if max_age is not None and time.time() - row.updated_at > max_age:
        return None
    return float(row.value)


# --- 응답 캐시 ---------------------------------------------------------------


def load_report(cache_key: str, ttl: int) -> dict | None:
    stmt = sa.select(reports.c.payload, reports.c.created_at).where(
        reports.c.cache_key == cache_key
    )
    with engine().connect() as conn:
        row = conn.execute(stmt).first()
    if row is None or time.time() - row.created_at > ttl:
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
            "last_ingest": conn.execute(
                sa.select(sa.func.max(instruments.c.prices_updated_at))
            ).scalar(),
        }
