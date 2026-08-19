"""공시값 산술로만 만드는 재무비율 — 양국 재무 lane이 공유한다.

허용 범위는 좁고 명시적이다: 같은 보고서(또는 같은 lane의 인접 연도 보고서)에
공시된 값들의 사칙연산뿐이다. 추정·보간·연율화는 하지 않는다.

- ROE = 순이익 ÷ 자본총계, ROA = 순이익 ÷ 자산총계 (연간 행만 — 분기 이익에
  적용하면 연율화 없이는 오독이라 아예 계산하지 않는다)
- 부채비율 = (자산총계 − 자본총계) ÷ 자본총계. 부채총계를 직접 공시받지 않는
  lane에서도 회계 항등식으로 성립하는 두 공시값의 산술이다.
- 매출 성장률 = 전년 공시 매출 대비. **연도가 정확히 1 차이 나는 행이 있을
  때만** 계산한다 — 결측 연도를 건너뛴 성장률은 오독이다.

분모가 0·음수인 비율은 null로 남긴다. 자본잠식 기업의 ROE 같은 값을
만들어내지 않기 위해서다.
"""

from __future__ import annotations

from typing import Any


def _ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        top = float(numerator)
        bottom = float(denominator)
    except (TypeError, ValueError):
        return None
    if bottom <= 0:
        return None
    return round(top / bottom * 100, 1)


def enrich_annual_rows(rows: list[dict[str, Any]], *, year_key: str) -> None:
    """연간 행(최신 우선 정렬)에 ROE·ROA·부채비율·매출 성장률을 더한다. 제자리 수정."""
    by_year: dict[int, dict[str, Any]] = {}
    for row in rows:
        year = row.get(year_key)
        if isinstance(year, int):
            by_year[year] = row
    for row in rows:
        net = row.get("net_income")
        assets = row.get("assets")
        equity = row.get("equity")
        row["roe"] = _ratio(net, equity)
        row["roa"] = _ratio(net, assets)
        if assets is not None and equity is not None:
            row["debt_ratio"] = _ratio(float(assets) - float(equity), equity)
        else:
            row["debt_ratio"] = None
        row["revenue_growth"] = None
        year = row.get(year_key)
        previous = by_year.get(year - 1) if isinstance(year, int) else None
        if previous is not None:
            revenue = row.get("revenue")
            prior = previous.get("revenue")
            try:
                if revenue is not None and prior is not None and float(prior) > 0:
                    row["revenue_growth"] = round(
                        (float(revenue) / float(prior) - 1.0) * 100, 1
                    )
            except (TypeError, ValueError):
                pass


def trailing_valuation(
    market_cap: float | None,
    net_income: Any,
    equity: Any,
) -> dict[str, Any] | None:
    """후행 PER·PBR: 최신 시가총액 ÷ 최근 연간 공시값.

    순이익이 0 이하이면 PER은 null이다 — 음수 PER은 숫자가 아니라 상태
    ("적자")이고, 그 상태는 이미 순이익 칸이 말해 준다.
    """
    if market_cap is None or market_cap <= 0:
        return None
    per = None
    try:
        net = float(net_income)
        if net > 0:
            per = round(market_cap / net, 1)
    except (TypeError, ValueError):
        pass
    pbr = None
    try:
        book = float(equity)
        if book > 0:
            pbr = round(market_cap / book, 2)
    except (TypeError, ValueError):
        pass
    if per is None and pbr is None:
        return None
    return {"per": per, "pbr": pbr}
