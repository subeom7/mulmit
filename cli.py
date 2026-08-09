"""터미널에서 바로 지표를 뽑는 CLI.

웹 없이 계산만 확인하고 싶을 때 쓴다. 웹과 완전히 같은 계산 코드를 부른다.

    python cli.py AAPL
    python cli.py AAPL --horizon 36 --drift zero
    python cli.py --corr AAPL MSFT GLD
"""

from __future__ import annotations

import argparse
import sys

from app import service
from app.data import DataError
from app.metrics.correlation import correlation_matrix

# 윈도우 콘솔은 기본이 cp949라 한글 외 기호에서 깨진다
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def pct(value, digits=1):
    return "-" if value is None else f"{value * 100:.{digits}f}%"


def num(value, digits=2):
    return "-" if value is None else f"{value:.{digits}f}"


def section(title):
    print(f"\n{title}")
    print("-" * 62)


def show_metrics(args) -> None:
    report = service.build_report(
        args.ticker,
        horizon_months=args.horizon,
        n_sims=args.sims,
        drift_mode=args.drift,
        lookback_years=args.lookback,
        include_series=False,
    )
    meta, basic = report["meta"], report["basic"]
    dd, capm, fc = report["drawdown"], report["capm"], report["forecast"]

    print(f"\n{report['ticker']}  {meta['name']}")
    print(f"{basic['last_price']:,.2f} {meta.get('currency') or ''}"
          f"  ({pct(basic['change_1d'])}, {basic['last_date']})")

    section(f"수익/위험  [{basic['window']['start']} ~ {basic['window']['end']}]")
    print(f"  연평균 수익률(CAGR) {pct(basic['cagr']):>9}    연 변동성 {pct(basic['annual_volatility']):>9}")
    print(f"  샤프 지수         {num(basic['sharpe_ratio']):>9}    소르티노  {num(basic['sortino_ratio']):>9}")

    section("낙폭")
    print(f"  역대 최대 낙폭     {pct(dd['max_drawdown']):>9}  ({dd['max_drawdown_date']})")
    print(f"  현재 낙폭         {pct(dd['current_drawdown']):>9}"
          + (f"  ({dd['underwater_since']}부터)" if dd["underwater_since"] else ""))
    print(f"  얼스터 지수       {num(dd['ulcer_index'], 3):>9}    칼마 비율 {num(dd['calmar_ratio']):>9}")
    print("\n  깊은 낙폭 구간")
    print(f"    {'낙폭':>8}  {'고점':<12}{'저점':<12}{'회복':<12}{'하락':>7}{'회복':>8}")
    for ep in dd["episodes"]:
        recovery = ep["recovery_date"] if ep["recovered"] else "미회복"
        days = f"{ep['recovery_days']:,}일" if ep["recovered"] else "-"
        print(f"    {pct(ep['depth']):>8}  {ep['peak_date']:<12}{ep['trough_date']:<12}"
              f"{recovery:<12}{ep['decline_days']:>6,}일{days:>8}")

    if capm.get("available"):
        section(f"CAPM  [{meta['market_index']} 대비]")
        basis = "지연보정" if capm["beta_basis"] == "lag_adjusted" else "당일"
        print(f"  베타({basis})      {num(capm['beta_effective']):>9}"
              f"    R^2 {pct(capm['r_squared_effective'], 0):>7}")
        print(f"  연 알파           {pct(capm['alpha_annual']):>9}"
              f"    기대수익률 {pct(capm['expected_return']):>7}")
        if capm["side_analysis_reliable"]:
            print(f"  상승장 베타       {num(capm['upside']['beta']):>9}"
                  f"    하락장 베타 {num(capm['downside']['beta']):>7}")
        else:
            print("  상승장/하락장 분해: 당일 회귀 신뢰도가 낮아 생략")

    if fc.get("available"):
        assume = fc["assumptions"]
        section(f"미래 최대낙폭 예측  [{fc['horizon_label']}, {fc['n_sims']:,}회 시뮬레이션]")
        print(f"  가정: 수익률 {assume['drift_mode']} 연 {pct(assume['annual_drift'])}"
              f" / 변동성 연 {pct(assume['annual_volatility'])}")
        print(f"\n    {'방법':<22}{'중앙값':>9}{'상위5%':>9}{'-20%초과':>10}{'-30%초과':>10}")
        names = {"block_bootstrap": "블록 부트스트랩(기본)", "student_t": "t분포 시뮬레이션",
                 "historical_windows": "과거 실증 구간"}
        for key, method in fc["methods"].items():
            print(f"    {names.get(key, key):<22}{pct(method['percentiles']['p50']):>9}"
                  f"{pct(method['percentiles']['p95']):>9}"
                  f"{pct(method['exceedance']['0.20'], 0):>10}"
                  f"{pct(method['exceedance']['0.30'], 0):>10}")
        for warning in fc["warnings"]:
            print(f"\n  [주의] {warning}")
    else:
        section("미래 최대낙폭 예측")
        print(f"  계산 불가: {fc.get('reason')}")

    section("해석")
    for note in report["notes"]:
        print(f"  - {note}")
    print()


def show_correlation(args) -> None:
    result = correlation_matrix(args.corr, period=args.period)
    print(f"\n일간 수익률 상관계수  [{result['start']} ~ {result['end']}, {result['trading_days']:,}일]\n")
    tickers = result["tickers"]
    print("           " + "".join(f"{t:>11}" for t in tickers))
    for row in tickers:
        cells = "".join(f"{result['matrix'][row][col]:>11.3f}" for col in tickers)
        print(f"{row:<11}{cells}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="주식 지표 계산기")
    parser.add_argument("ticker", nargs="?", help="예: AAPL, 005930.KS, BTC-USD")
    parser.add_argument("--horizon", type=int, default=12, help="예측 구간(개월, 기본 12)")
    parser.add_argument("--sims", type=int, default=5000, help="시뮬레이션 횟수")
    parser.add_argument("--drift", default="historical",
                        choices=["historical", "zero", "capm"], help="미래 수익률 가정")
    parser.add_argument("--lookback", type=int, default=10, help="분석 기간(년)")
    parser.add_argument("--corr", nargs="+", metavar="TICKER", help="티커 간 상관계수")
    parser.add_argument("--period", default="1y", help="--corr 기간 (1y, 5y, max ...)")
    args = parser.parse_args()

    try:
        if args.corr:
            show_correlation(args)
        elif args.ticker:
            show_metrics(args)
        else:
            parser.print_help()
    except DataError as exc:
        print(f"\n오류: {exc}\n", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\n오류: {exc}\n", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
