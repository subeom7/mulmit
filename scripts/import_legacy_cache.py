"""예전 피클 디스크 캐시(.cache/*.pkl)를 새 저장소로 옮긴다.

Phase 0 이전 버전은 `sha1("history:AAPL:max")[:16].pkl` 같은 이름으로
DataFrame을 피클해 뒀다. 파일명만 봐선 어느 티커인지 알 수 없으므로
후보 티커의 해시를 거꾸로 계산해 맞춘다.

한 번 쓰고 버리는 스크립트지만 남겨 둔다 — 야후가 막혀 있을 때
이미 받아 둔 데이터를 되살릴 수 있는 유일한 경로다.

    python scripts/import_legacy_cache.py
    python scripts/import_legacy_cache.py --cache-dir .cache --extra TSLA NVDA
"""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import store  # noqa: E402
from app.providers.base import DataUnavailable, normalize_close  # noqa: E402

# 예전 코드가 쓰던 기간 값
PERIODS = ["max", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "5d"]

# 지금까지 이 앱에서 조회했을 법한 티커들. --extra로 더 넣을 수 있다.
CANDIDATES = [
    "^GSPC", "^TNX", "^IXIC", "^DJI", "^KS11",
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "SPY", "QQQ", "VOO", "VTI", "GLD", "TLT", "IWM", "SCHD",
    "SKHY", "NBIS", "PLTR", "AMD", "INTC", "NFLX", "AVGO", "COIN",
    "BTC-USD", "ETH-USD",
    "005930.KS", "000660.KS", "035720.KS", "005380.KS", "051910.KS",
]


def legacy_key_map(tickers: list[str]) -> dict[str, tuple[str, str]]:
    """digest -> (kind, ticker). kind는 history/info/macro."""
    out: dict[str, tuple[str, str]] = {}

    def add(key: str, kind: str, ticker: str) -> None:
        out[hashlib.sha1(key.encode()).hexdigest()[:16]] = (kind, ticker)

    for ticker in tickers:
        add(f"info:{ticker}", "info", ticker)
        for period in PERIODS:
            add(f"history:{ticker}:{period}", "history", ticker)
    add("macro:riskfree", "macro", "riskfree")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="예전 피클 캐시 → 저장소 이관")
    parser.add_argument("--cache-dir", default=".cache")
    parser.add_argument("--extra", nargs="*", default=[], help="추가 후보 티커")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_dir():
        print(f"캐시 디렉터리가 없습니다: {cache_dir}")
        return 1

    tickers = CANDIDATES + [t.strip().upper() for t in args.extra if t.strip()]
    mapping = legacy_key_map(tickers)

    store.init_db()
    imported = skipped = 0

    for path in sorted(cache_dir.glob("*.pkl")):
        entry = mapping.get(path.stem)
        if entry is None:
            print(f"  ? {path.name}  (후보에 없는 티커 — --extra로 추가해 보세요)")
            skipped += 1
            continue

        kind, ticker = entry
        try:
            value = pickle.loads(path.read_bytes())
        except Exception as exc:
            print(f"  ! {path.name}  읽기 실패: {exc}")
            skipped += 1
            continue

        try:
            if kind == "history" and isinstance(value, pd.DataFrame) and "Close" in value:
                rows = store.save_prices(ticker, normalize_close(value["Close"], ticker))
                print(f"  + {ticker:<12} 가격 {rows:,}행")
                imported += 1
            elif kind == "info" and isinstance(value, dict) and value:
                store.save_info(ticker, value)
                print(f"  + {ticker:<12} 종목정보")
                imported += 1
            elif kind == "macro" and isinstance(value, (int, float)):
                store.save_macro("riskfree", float(value))
                print(f"  + 무위험수익률 {float(value):.4f}")
                imported += 1
            else:
                skipped += 1
        except DataUnavailable as exc:
            print(f"  - {ticker:<12} 건너뜀: {exc}")
            skipped += 1

    print(f"\n이관 {imported}건, 건너뜀 {skipped}건")
    print("저장소 상태:", store.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
