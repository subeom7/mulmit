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
# 조립된 리포트 응답 캐시. 시드가 고정이라 같은 입력이면 결과가 같다.
REPORT_TTL = _int("REPORT_TTL", 60 * 60 * 24)
# 없는 티커를 기억해 두는 시간(같은 오타로 야후를 계속 두드리지 않도록)
NEGATIVE_TTL = _int("NEGATIVE_TTL", 60 * 60 * 6)

# --- 수집 배치 ---------------------------------------------------------------
INGEST_ENABLED = _bool("INGEST_ENABLED", True)
INGEST_INTERVAL = _int("INGEST_INTERVAL", 60 * 60)  # 스케줄러 기동 주기(초)
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
# 유료 API로 갈아탈 때 여기만 바꾼다. providers/__init__.py 참고.
PROVIDER = os.environ.get("PROVIDER", "yahoo")
