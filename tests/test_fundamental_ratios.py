"""공시값 산술 재무비율.

고정하는 것: 분모가 0·음수인 비율은 null(자본잠식 ROE를 만들지 않는다),
성장률은 연속 연도에만 성립(결측 연도 건너뛰기 금지), 후행 PER은 적자에서
null, 부채비율은 (자산−자본)÷자본 항등식이다.
"""

from __future__ import annotations

from app.fundamental_ratios import enrich_annual_rows, trailing_valuation


def _row(year, revenue=None, net=None, assets=None, equity=None):
    return {
        "year": year, "revenue": revenue, "net_income": net,
        "assets": assets, "equity": equity,
    }


def test_ratios_are_filed_value_arithmetic():
    rows = [
        _row(2025, revenue=110.0, net=20.0, assets=400.0, equity=200.0),
        _row(2024, revenue=100.0, net=10.0, assets=380.0, equity=190.0),
    ]
    enrich_annual_rows(rows, year_key="year")

    latest = rows[0]
    assert latest["roe"] == 10.0          # 20 / 200
    assert latest["roa"] == 5.0           # 20 / 400
    assert latest["debt_ratio"] == 100.0  # (400-200) / 200
    assert latest["revenue_growth"] == 10.0
    assert rows[1]["revenue_growth"] is None  # 전년 행이 없다


def test_gap_years_do_not_fake_growth():
    rows = [
        _row(2025, revenue=200.0),
        _row(2023, revenue=100.0),  # 2024가 비어 있다 — 2년 성장률을 1년처럼 내면 안 된다
    ]
    enrich_annual_rows(rows, year_key="year")
    assert rows[0]["revenue_growth"] is None


def test_impaired_equity_yields_null_not_a_number():
    rows = [_row(2025, net=10.0, assets=100.0, equity=-5.0)]
    enrich_annual_rows(rows, year_key="year")
    assert rows[0]["roe"] is None
    assert rows[0]["debt_ratio"] is None


def test_trailing_valuation_withholds_per_on_losses():
    both = trailing_valuation(1000.0, 100.0, 500.0)
    assert both == {"per": 10.0, "pbr": 2.0}

    loss = trailing_valuation(1000.0, -50.0, 500.0)
    assert loss["per"] is None
    assert loss["pbr"] == 2.0

    assert trailing_valuation(None, 100.0, 500.0) is None
    assert trailing_valuation(1000.0, -1.0, -1.0) is None
