"""티커 하나 → 대시보드에 필요한 모든 지표를 조립한다.

기간 선택 기준:
  - 낙폭/수익률: 전체 상장 이력 (2008, 코로나 같은 큰 사건을 놓치면 안 됨)
  - CAPM/시뮬레이션: 최근 N년 (기본 10년, 오래된 사업 구조는 지금과 무관)
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from . import __version__, config, data, store
from .metrics import basic, capm, drawdown, forecast


def sanitize(obj: Any) -> Any:
    """JSON으로 나갈 수 없는 값을 정리.

    NaN/Inf는 JSON 표준이 아니라서 Starlette이 직렬화하다 500을 낸다
    (베타나 PER이 없는 종목에서 실제로 터진다). numpy 스칼라도 여기서 흡수.
    """
    if isinstance(obj, dict):
        return {key: sanitize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(value) for value in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    return obj


def _slice_recent(close: pd.Series, years: int) -> pd.Series:
    cutoff = close.index[-1] - pd.Timedelta(days=int(years * 365.25))
    window = close[close.index >= cutoff]
    return window if len(window) >= 30 else close


def _finite(value: Any) -> float | None:
    """숫자이고 NaN/Inf가 아니면 float으로, 아니면 None."""
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def _pct(value: float | None, digits: int = 1) -> str:
    value = _finite(value)
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _interpret(report: dict) -> list[str]:
    """숫자를 사람이 읽는 한 줄로. 투자 조언이 아니라 사실 서술만."""
    notes: list[str] = []
    dd = report["drawdown"]
    cp = report["capm"]
    fc = report["forecast"]

    beta = _finite(cp.get("beta_effective")) if cp.get("available") else None
    if beta is not None:
        notes.append(
            f"베타 {beta:.2f} — 시장이 1% 움직일 때 평균 {beta:.2f}% 움직였습니다"
            f" (설명력 R²={_pct(cp.get('r_squared_effective'))})."
        )
        same_day = _finite(cp.get("beta"))
        if cp.get("beta_basis") == "lag_adjusted" and same_day is not None:
            notes.append(
                f"{config.MARKET_TICKER}와 거래시간이 어긋나는 종목이라 지연보정 베타를 "
                f"썼습니다(당일 기준으로는 {same_day:.2f}로 과소평가됩니다)."
            )
        # 상승장/하락장 비대칭은 당일 회귀에서만 나온다. 그 회귀가 못 믿을
        # 상태면 숫자를 보여주는 것보다 결론을 내지 않는 편이 낫다.
        up = _finite(cp["upside"].get("beta")) if cp.get("side_analysis_reliable") else None
        down = _finite(cp["downside"].get("beta")) if cp.get("side_analysis_reliable") else None
        if up is not None and down is not None:
            if down > up * 1.1:
                notes.append(
                    f"하락장 베타({down:.2f})가 상승장 베타({up:.2f})보다 큽니다. "
                    "덜 오르고 더 빠지는 비대칭 구조입니다."
                )
            elif up > down * 1.1:
                notes.append(
                    f"상승장 베타({up:.2f})가 하락장 베타({down:.2f})보다 큽니다. "
                    "상승장에서 더 먹고 하락장에서 덜 맞는 비대칭 구조입니다."
                )

    worst = dd["episodes"][0] if dd["episodes"] else None
    if worst:
        tail = (
            f"회복까지 {worst['recovery_days']:,}일 걸렸습니다."
            if worst["recovered"]
            else "아직 회복하지 못했습니다."
        )
        notes.append(
            f"역대 최대 낙폭 {_pct(worst['depth'])} "
            f"({worst['peak_date']} → {worst['trough_date']}). {tail}"
        )

    current = dd["current_drawdown"]
    if current < -0.005:
        since = f" ({dd['underwater_since']}부터)" if dd.get("underwater_since") else ""
        notes.append(f"현재 전고점 대비 {_pct(current)} 지점입니다{since}.")
    else:
        notes.append("현재 전고점 부근입니다.")

    if fc.get("available"):
        head = fc["headline"]
        notes.append(
            f"향후 {fc['horizon_label']} MDD 중앙값 {_pct(head['median_mdd'])}, "
            f"상위 5% 악조건 {_pct(head['bad_case_mdd'])}. "
            f"20% 이상 빠질 확률 {_pct(head['prob_over_20pct'], 0)}."
        )

    return notes


def _cache_key(ticker: str, last_date: pd.Timestamp, params: tuple) -> str:
    """리포트 캐시 키.

    RANDOM_SEED가 고정이라 (티커, 파라미터, 마지막 거래일)이 같으면 결과도
    같다. 그래서 조립된 응답을 통째로 캐시해도 안전하다.

    앱 버전을 섞는 이유: 계산 로직이 바뀐 배포에서 옛 결과가 살아 있으면
    안 된다. __version__을 올리면 캐시가 통째로 무효화된다.
    """
    raw = "|".join(
        [__version__, ticker, last_date.strftime("%Y-%m-%d"), *map(repr, params)]
    )
    return hashlib.sha1(raw.encode()).hexdigest()


def build_report(
    ticker: str,
    horizon_months: int = config.DEFAULT_HORIZON_MONTHS,
    n_sims: int = config.DEFAULT_SIMS,
    drift_mode: str = "historical",
    custom_annual_drift: float | None = None,
    lookback_years: int = config.DEFAULT_LOOKBACK_YEARS,
    include_series: bool = True,
) -> dict:
    ticker = ticker.strip().upper()
    close = data.get_close(ticker)

    key = _cache_key(
        ticker,
        close.index[-1],
        (horizon_months, n_sims, drift_mode, custom_annual_drift,
         lookback_years, include_series),
    )
    cached = store.load_report(key, config.REPORT_TTL)
    if cached is not None:
        return cached

    info = data.get_info(ticker)
    risk_free = data.get_risk_free_rate()

    close_recent = _slice_recent(close, lookback_years)

    # 시장 지수는 조회에 실패해도 나머지 지표는 살아야 한다
    try:
        market = data.get_market_close()
        market_recent = market[market.index >= close_recent.index[0]]
        capm_result = capm.analyze(
            close_recent,
            market_recent,
            risk_free_rate=risk_free,
            beta_from_provider=info.get("beta"),
        )
    except Exception as exc:
        capm_result = {"available": False, "reason": f"시장 지수 조회 실패: {exc}"}

    forecast_result = forecast.forecast_mdd(
        close_recent,
        horizon_months=horizon_months,
        n_sims=n_sims,
        drift_mode=drift_mode,
        custom_annual_drift=custom_annual_drift,
        capm_expected_return=capm_result.get("expected_return") if capm_result.get("available") else None,
    )

    report = {
        "ticker": ticker,
        "meta": {
            "name": info.get("longName") or info.get("shortName") or ticker,
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "forward_pe": info.get("forwardPE"),
            "trailing_pe": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "market_index": config.MARKET_TICKER,
            "lookback_years": lookback_years,
        },
        "basic": basic.analyze(close_recent, risk_free, full_close=close),
        "drawdown": drawdown.analyze(close),
        "capm": capm_result,
        "forecast": forecast_result,
    }
    report["notes"] = _interpret(report)

    if include_series:
        underwater = drawdown.drawdown_series(close)
        report["series"] = {
            "dates": [d.strftime("%Y-%m-%d") for d in close.index],
            "close": [round(float(v), 4) for v in close.to_numpy()],
            "drawdown": [round(float(v), 5) for v in underwater.to_numpy()],
        }

    report = sanitize(report)
    store.save_report(key, report)
    return report
