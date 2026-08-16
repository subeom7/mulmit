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
        or fetched[series_id][0] < cutoff
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
            "fred_series": conn.execute(
                sa.select(sa.func.count()).select_from(fred_series)
            ).scalar_one(),
            "fred_observations": conn.execute(
                sa.select(sa.func.count()).select_from(fred_observations)
            ).scalar_one(),
            "last_fred_ingest": conn.execute(
                sa.select(sa.func.max(fred_series.c.fetched_at))
            ).scalar(),
            "last_ingest": conn.execute(
                sa.select(sa.func.max(instruments.c.prices_updated_at))
            ).scalar(),
        }
