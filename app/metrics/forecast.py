"""미래 MDD 예측 (몬테카를로).

중요: 미래 MDD는 점 예측이 불가능하다. "내년에 -32% 빠진다" 같은 숫자는
의미가 없다. 대신 수익률 경로를 수천 개 시뮬레이션해서 **MDD의 확률분포**를
만들고 "1년 안에 -30% 이상 빠질 확률 22%" 형태로 제시한다.

세 가지 방법을 함께 계산해서 서로 교차검증한다.

1. block_bootstrap (기본)
   과거 일간 수익률을 20일 블록 단위로 복원추출. 블록으로 뽑기 때문에
   변동성 군집(폭락은 폭락끼리 몰려온다)과 꼬리 위험이 보존된다.
   분포 가정이 없다는 게 최대 장점.

2. student_t
   t분포 GBM. 과거 첨도로 자유도를 추정해 팻테일을 반영한다.
   과거에 없던 크기의 충격도 만들어낼 수 있어 부트스트랩을 보완한다.

3. historical_windows
   과거 실제 N거래일 구간들의 MDD 실증분포. 시뮬레이션이 현실에서
   너무 벗어나지 않았는지 확인하는 기준선.

한계: 세 방법 모두 "미래의 변동성 구조가 과거와 비슷하다"고 가정한다.
체제 전환(레버리지 축소, 사업모델 변화, 상장 초기 종목)에는 약하다.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from .. import config
from .common import periods_per_year
from .drawdown import rolling_window_mdd

# 낙폭 확률을 물어볼 임계값들
EXCEEDANCE_LEVELS = (0.10, 0.20, 0.30, 0.40, 0.50)
PERCENTILES = (5, 25, 50, 75, 90, 95, 99)

Sampler = Callable[[int], np.ndarray]


def log_returns(close: pd.Series) -> np.ndarray:
    """일간 로그수익률."""
    prices = close.to_numpy(dtype="float64")
    return np.diff(np.log(prices))


# --------------------------------------------------------------------------
# 시뮬레이션 엔진
# --------------------------------------------------------------------------

def _path_stats(log_paths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """경로별 (MDD, 최종수익률).

    경로 시작 시점(수익률 0)도 고점 후보에 포함해야 한다. 첫날부터 하락하는
    경로에서 running max가 음수로 시작하면 낙폭을 과소평가한다.
    """
    cum = np.cumsum(log_paths, axis=1)
    peak = np.maximum(np.maximum.accumulate(cum, axis=1), 0.0)
    mdd = np.expm1(cum - peak).min(axis=1)
    terminal = np.expm1(cum[:, -1])
    return mdd, terminal


def _simulate(sampler: Sampler, n_sims: int, chunk: int) -> tuple[np.ndarray, np.ndarray]:
    """청크 단위로 돌려 메모리 사용량을 일정하게 유지한다."""
    mdd = np.empty(n_sims, dtype="float64")
    terminal = np.empty(n_sims, dtype="float64")
    done = 0
    while done < n_sims:
        size = min(chunk, n_sims - done)
        batch_mdd, batch_terminal = _path_stats(sampler(size))
        mdd[done:done + size] = batch_mdd
        terminal[done:done + size] = batch_terminal
        done += size
    return mdd, terminal


def _block_bootstrap_sampler(
    returns: np.ndarray, horizon: int, block_size: int, rng: np.random.Generator
) -> Sampler:
    """순환 블록 부트스트랩. 끝에서 앞으로 감아 모든 시점을 균등하게 뽑는다."""
    n = len(returns)
    n_blocks = int(np.ceil(horizon / block_size))
    offsets = np.arange(block_size)

    def sample(size: int) -> np.ndarray:
        starts = rng.integers(0, n, size=(size, n_blocks))
        idx = (starts[:, :, None] + offsets) % n
        return returns[idx].reshape(size, n_blocks * block_size)[:, :horizon]

    return sample


def _student_t_sampler(
    mu: float, sigma: float, nu: float, horizon: int, rng: np.random.Generator
) -> Sampler:
    # standard_t의 분산은 nu/(nu-2)라서 목표 sigma에 맞춰 되돌려 스케일한다
    scale = sigma * np.sqrt((nu - 2.0) / nu)

    def sample(size: int) -> np.ndarray:
        return mu + scale * rng.standard_t(nu, size=(size, horizon))

    return sample


def _estimate_nu(returns: np.ndarray) -> float:
    """초과첨도로 t분포 자유도 추정: 초과첨도 = 6/(nu-4)."""
    std = returns.std(ddof=1)
    if std <= 0:
        return 30.0
    z = (returns - returns.mean()) / std
    excess = float(np.mean(z ** 4) - 3.0)
    if excess <= 0.1:
        return 30.0  # 사실상 정규분포
    return float(np.clip(4.0 + 6.0 / excess, 3.0, 30.0))


# --------------------------------------------------------------------------
# 결과 요약
# --------------------------------------------------------------------------

def _summarize(mdd: np.ndarray, terminal: np.ndarray | None = None) -> dict:
    """MDD 표본 → 분위수 / 초과확률 / 히스토그램.

    분위수 키는 '심각도 기준'이다. p95는 "95% 확률로 이보다 얕게 끝난다"
    = 상위 5% 악조건. 값 자체는 음수로 유지한다.
    """
    severity = -mdd  # 양수로 뒤집어야 분위수 방향이 직관적이다
    out: dict = {
        "n": int(len(mdd)),
        "mean": float(mdd.mean()),
        "percentiles": {
            f"p{p}": float(-np.quantile(severity, p / 100.0)) for p in PERCENTILES
        },
        "exceedance": {
            f"{level:.2f}": float((severity >= level).mean()) for level in EXCEEDANCE_LEVELS
        },
        # 최악 5% 경로들의 평균 낙폭 (CVaR 개념)
        "expected_shortfall_95": float(mdd[severity >= np.quantile(severity, 0.95)].mean()),
    }

    upper = float(np.clip(np.quantile(severity, 0.995) * 1.05, 0.10, 1.0))
    counts, edges = np.histogram(severity, bins=40, range=(0.0, upper))
    out["histogram"] = {
        "bin_edges": [float(-e) for e in edges],
        "probs": [float(c / len(severity)) for c in counts],
    }

    if terminal is not None:
        out["terminal_return"] = {
            "median": float(np.quantile(terminal, 0.50)),
            "p5": float(np.quantile(terminal, 0.05)),
            "p95": float(np.quantile(terminal, 0.95)),
            "prob_loss": float((terminal < 0).mean()),
        }
    return out


def _resolve_drift(
    returns: np.ndarray,
    mode: str,
    custom_annual: float | None,
    capm_annual: float | None,
    ppy: int,
) -> tuple[float, float, str]:
    """드리프트 모드 → (일간 로그드리프트, 연 CAGR 가정, 실제 적용된 모드).

    과거 드리프트를 그대로 쓰면 최근 급등주는 미래 수익률을 터무니없이
    낙관하게 된다(그래서 UI에 0% 가정 토글을 뒀다).
    """
    if mode == "zero":
        daily = 0.0
    elif mode == "capm" and capm_annual is not None and np.isfinite(capm_annual):
        daily = float(np.log1p(max(capm_annual, -0.99)) / ppy)
    elif mode == "custom" and custom_annual is not None:
        daily = float(np.log1p(max(custom_annual, -0.99)) / ppy)
    else:
        mode = "historical"
        daily = float(returns.mean())

    annual_cagr = float(np.expm1(daily * ppy))
    return daily, annual_cagr, mode


# --------------------------------------------------------------------------
# 공개 API
# --------------------------------------------------------------------------

def forecast_mdd(
    close: pd.Series,
    horizon_months: int = 12,
    n_sims: int = config.DEFAULT_SIMS,
    drift_mode: str = "historical",
    custom_annual_drift: float | None = None,
    capm_expected_return: float | None = None,
    block_size: int = config.BLOCK_SIZE,
    seed: int | None = config.RANDOM_SEED,
) -> dict:
    """향후 `horizon_months`개월 동안의 MDD 확률분포.

    구간을 거래일이 아니라 개월로 받는 이유: 1년이 주식은 252거래일,
    크립토는 365일이라 자산마다 다르다. 여기서 데이터를 보고 환산한다.

    close는 시뮬레이션 표본으로 쓸 구간만 잘라서 넘길 것(보통 최근 10년).
    """
    returns = log_returns(close)
    n = len(returns)
    ppy = periods_per_year(close)
    horizon = max(5, int(round(ppy * horizon_months / 12)))

    if n < 60:
        return {
            "available": False,
            "reason": f"수익률 표본이 {n}일뿐입니다. 최소 60거래일이 필요합니다.",
        }

    warnings: list[str] = []
    if n < 3 * ppy:
        warnings.append(
            f"표본이 {n / ppy:.1f}년으로 짧아 꼬리 위험이 과소평가될 수 있습니다. "
            "특히 이 종목은 아직 약세장을 겪지 않았을 수 있습니다."
        )
    if horizon > n / 3:
        warnings.append(
            f"예측 구간({horizon_months}개월)이 과거 표본({n / ppy:.1f}년)에 비해 깁니다. "
            "결과를 참고용으로만 보세요."
        )

    # 블록이 표본에 비해 너무 길면 사실상 같은 구간만 반복 추출하게 된다
    block_size = int(np.clip(block_size, 1, max(1, n // 5)))

    daily_drift, annual_drift, drift_mode = _resolve_drift(
        returns, drift_mode, custom_annual_drift, capm_expected_return, ppy
    )
    daily_vol = float(returns.std(ddof=1))
    annual_vol = daily_vol * np.sqrt(ppy)

    rng = np.random.default_rng(seed)

    # 부트스트랩: 평균만 목표 드리프트로 갈아끼우고 나머지 구조는 그대로 둔다
    centered = returns - returns.mean() + daily_drift
    boot_mdd, boot_terminal = _simulate(
        _block_bootstrap_sampler(centered, horizon, block_size, rng),
        n_sims,
        config.SIM_CHUNK,
    )

    nu = _estimate_nu(returns)
    t_mdd, t_terminal = _simulate(
        _student_t_sampler(daily_drift, daily_vol, nu, horizon, rng),
        n_sims,
        config.SIM_CHUNK,
    )

    methods = {
        "block_bootstrap": _summarize(boot_mdd, boot_terminal),
        "student_t": _summarize(t_mdd, t_terminal),
    }
    methods["block_bootstrap"]["block_size"] = block_size
    methods["student_t"]["nu"] = round(nu, 2)

    # 실증 기준선은 실제 과거 가격이라 드리프트 가정이 개입하지 않는다
    empirical = rolling_window_mdd(close, horizon)
    if len(empirical) >= 30:
        methods["historical_windows"] = _summarize(empirical)
        methods["historical_windows"]["note"] = (
            f"과거 {len(empirical)}개 구간(중첩)의 실제 MDD. 드리프트 가정 없음."
        )

    primary = methods["block_bootstrap"]
    return {
        "available": True,
        "primary_method": "block_bootstrap",
        "horizon_months": horizon_months,
        "horizon_days": horizon,
        "horizon_label": _horizon_label(horizon_months),
        "n_sims": n_sims,
        "sample_days": n,
        "sample_start": close.index[0].strftime("%Y-%m-%d"),
        "assumptions": {
            "drift_mode": drift_mode,
            "annual_drift": annual_drift,
            "annual_volatility": annual_vol,
            "periods_per_year": ppy,
            "seed": seed,
        },
        "headline": {
            # 가장 그럴듯한 값(중앙값)과 꼬리 위험을 같이 보여준다
            "median_mdd": primary["percentiles"]["p50"],
            "bad_case_mdd": primary["percentiles"]["p95"],  # 상위 5% 악조건
            "expected_shortfall_95": primary["expected_shortfall_95"],
            "prob_over_20pct": primary["exceedance"]["0.20"],
            "prob_over_30pct": primary["exceedance"]["0.30"],
        },
        "methods": methods,
        "warnings": warnings,
    }


def _horizon_label(months: int) -> str:
    if months >= 12 and months % 12 == 0:
        return f"{months // 12}년"
    return f"{months}개월"
