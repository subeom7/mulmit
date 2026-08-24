"""13F 기관 포트폴리오 — 서식의 함정을 기계로 묶는다.

이 lane에서 조용히 틀리는 자리는 셋이고, 셋 다 실측으로 확인한 것이다
(2026-08-24, EDGAR 라이브).

1. **금액 단위가 제출자마다 다르다.** 버크셔는 달러, 두케인은 천 달러다.
   섞으면 천 배 틀린 그림이 아무 오류 없이 나온다.
2. **한 종목이 여러 행으로 온다.** 버크셔의 최근 제출은 89행인데 발행사는
   26곳이다. 합치지 않으면 애플이 파이에 여러 조각으로 나타난다.
3. **조각 수를 20으로 못 박으면 브리지워터가 규칙을 깬다.** 상위 20이
   49.8%라 이름 붙은 조각이 과반이 안 된다 — 그림이 보유 종목이 아니라
   나머지를 말하게 된다.

여기 있는 검사는 대부분 기능이 아니라 **그림이 거짓말하지 않는 성질**을
지킨다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import us_managers
from app.main import app
from app.providers.sec_edgar import (
    FORM_13F_THRESHOLD_USD,
    ManagerHolding,
    ManagerPortfolio,
    _normalise_scale,
    _parse_info_table,
)

client = TestClient(app)

TODAY = dt.date(2026, 8, 24)


def _holding(issuer: str, value: float, *, option: bool = False) -> ManagerHolding:
    return ManagerHolding(issuer=issuer, cusip="", value_usd=value, shares=None, is_option=option)


def _portfolio(holdings: list[ManagerHolding], **kw) -> ManagerPortfolio:
    defaults = {
        "cik": "0000000001", "name": "TEST FILER", "form": "13F-HR",
        "filed": dt.date(2026, 8, 14), "period": dt.date(2026, 6, 30),
        "accession": "000", "row_count": len(holdings), "value_scale": "dollars",
        "options_value_usd": sum(h.value_usd for h in holdings if h.is_option),
    }
    defaults.update(kw)
    return ManagerPortfolio(holdings=tuple(holdings), **defaults)


# --- 1. 단위 --------------------------------------------------------------

def test_a_total_below_the_filing_threshold_must_be_thousands():
    """13F는 1억 달러 이상일 때만 의무다. 합계가 그보다 작으면 달러가 아니다.

    두케인 실측: 합계 5.211e6. 달러로 읽으면 $5.2M인데 그 규모면 애초에 신고
    의무가 없다 — 즉 천 단위이고 실제로는 $5.21B다.
    """
    small = [_holding("A", 5_000_000.0), _holding("B", 211_000.0)]
    scale, scaled, _ = _normalise_scale(tuple(small), 0.0)

    assert scale == "thousands"
    assert sum(h.value_usd for h in scaled) == pytest.approx(5_211_000_000.0)


def test_a_total_above_the_threshold_is_left_alone():
    big = [_holding("A", 2.993e11)]
    scale, scaled, _ = _normalise_scale(tuple(big), 0.0)

    assert scale == "dollars"
    assert scaled[0].value_usd == pytest.approx(2.993e11)


def test_the_threshold_is_the_one_the_form_uses():
    assert FORM_13F_THRESHOLD_USD == 100_000_000


# --- 2. 행 합치기 ----------------------------------------------------------

def test_rows_are_merged_by_issuer():
    """운용 재량이 갈리면 한 종목이 여러 행으로 온다."""
    from xml.etree import ElementTree

    xml = """<informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf">
      <ns1:infoTable><ns1:nameOfIssuer>APPLE INC</ns1:nameOfIssuer>
        <ns1:cusip>037833100</ns1:cusip><ns1:value>60</ns1:value>
        <ns1:sshPrnamt>6</ns1:sshPrnamt></ns1:infoTable>
      <ns1:infoTable><ns1:nameOfIssuer>APPLE INC</ns1:nameOfIssuer>
        <ns1:cusip>037833100</ns1:cusip><ns1:value>40</ns1:value>
        <ns1:sshPrnamt>4</ns1:sshPrnamt></ns1:infoTable>
      <ns1:infoTable><ns1:nameOfIssuer>COCA COLA CO</ns1:nameOfIssuer>
        <ns1:cusip>191216100</ns1:cusip><ns1:value>25</ns1:value>
        <ns1:sshPrnamt>2</ns1:sshPrnamt></ns1:infoTable>
    </informationTable>"""
    root = ElementTree.fromstring(xml)
    blocks = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "infoTable"]

    holdings, rows, _ = _parse_info_table(blocks)

    assert rows == 3, "원래 행 수를 잃으면 화면이 '89행 → 26곳'을 말할 수 없다"
    assert [h.issuer for h in holdings] == ["APPLE INC", "COCA COLA CO"]
    assert holdings[0].value_usd == 100
    assert holdings[0].shares == 10


def test_the_namespace_prefix_is_ignored():
    """접두어를 그대로 찾다가 브리지워터·피셔가 통째로 빠졌다(2026-08-24)."""
    from xml.etree import ElementTree

    for opening, closing in (("<infoTable>", "</infoTable>"), ("<x:infoTable>", "</x:infoTable>")):
        prefix = ' xmlns:x="urn:x"' if "x:" in opening else ""
        tag = "x:" if "x:" in opening else ""
        xml = (f"<root{prefix}>{opening}<{tag}nameOfIssuer>A</{tag}nameOfIssuer>"
               f"<{tag}value>500</{tag}value>{closing}</root>")
        root = ElementTree.fromstring(xml)
        blocks = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1] == "infoTable"]
        holdings, _, _ = _parse_info_table(blocks)
        assert len(holdings) == 1, opening


# --- 3. 조각 수 규칙 --------------------------------------------------------

def test_named_slices_reach_a_majority_even_when_it_needs_more_than_twenty():
    """브리지워터 실측: 상위 20이 49.8%, 21에서 처음 과반이 된다.

    20으로 못 박으면 이 신고자만 규칙을 깨고, 그림이 보유 종목이 아니라
    나머지를 말하게 된다.
    """
    # 상위 20이 49.5%, 21번째를 넣어야 50.5%가 되는 분포 — 브리지워터와 같은 모양.
    holdings = (
        [_holding(f"N{i}", 2.475) for i in range(20)]
        + [_holding("EDGE", 1.0)]
        + [_holding(f"T{i}", 0.5) for i in range(99)]
    )
    total = sum(h.value_usd for h in holdings)
    assert sum(h.value_usd for h in holdings[:20]) / total < 0.5, "픽스처가 이미 과반이다"
    rows = [{"issuer": h.issuer, "value": h.value_usd} for h in holdings]

    count, short = us_managers._slice_count(rows, total)

    assert count > us_managers.BASE_SLICES, "20에서 멈췄다 — 과반 규칙이 안 걸린다"
    assert not short
    assert sum(r["value"] for r in rows[:count]) / total > 0.5


def test_a_hopeless_tail_is_capped_and_flagged():
    """아무리 늘려도 과반이 안 되는 분포는 그 사실을 화면이 말해야 한다."""
    rows = [{"issuer": f"S{i}", "value": 1.0} for i in range(400)]
    count, short = us_managers._slice_count(rows, 400.0)

    assert count == us_managers.MAX_SLICES
    assert short is True


def test_a_small_book_shows_every_name():
    """퍼싱 실측: 발행사가 10곳뿐이라 `기타`가 아예 없다."""
    rows = [{"issuer": f"S{i}", "value": 10.0} for i in range(10)]
    count, short = us_managers._slice_count(rows, 100.0)

    assert count == 10
    assert not short


# --- 4. 카드 조립 -----------------------------------------------------------

@pytest.fixture
def card() -> dict:
    holdings = [_holding(f"NAME {i}", 100.0 - i) for i in range(40)]
    holdings.append(_holding("SPDR S&P 500 ETF", 60.0))
    holdings.append(_holding("PUT SOMETHING", 40.0, option=True))
    holdings.sort(key=lambda h: -h.value_usd)
    portfolio = _portfolio(holdings, options_value_usd=40.0)
    return us_managers._build_manager(us_managers.MANAGERS[0], portfolio, TODAY)


def test_the_angles_close_the_circle(card):
    """조각의 합이 100이 아니면 도넛에 빈 틈이 생긴다."""
    assert sum(s["share"] for s in card["slices"]) == pytest.approx(100.0, abs=1e-9)


def test_the_rest_slice_carries_everything_not_named(card):
    named = [s for s in card["slices"] if s["kind"] == "holding"]
    rest = [s for s in card["slices"] if s["kind"] == "rest"]

    assert len(named) == card["totals"]["slice_count"]
    assert len(rest) == 1
    assert rest[0]["count"] == card["totals"]["issuers"] - len(named)


def test_options_and_index_shares_are_measured_not_asserted(card):
    """배지 문구는 손으로 적지 않는다 — 데이터가 바뀌면 조용히 거짓이 된다."""
    totals = card["totals"]
    assert totals["options_share"] > 0
    assert totals["index_share"] > 0, "지수 상품 휴리스틱이 SPDR을 못 잡았다"


def test_the_lag_travels_with_the_card(card):
    """퍼싱 실측 147일. 얼마나 낡았는지를 화면이 말할 수 있어야 한다."""
    assert card["period"] == "2026-06-30"
    assert card["period_lag_days"] == (TODAY - dt.date(2026, 6, 30)).days


def test_the_filing_url_points_at_the_original(card):
    assert card["filing_url"].startswith("https://www.sec.gov/Archives/edgar/data/")


# --- 5. 사람에 관한 사실 ----------------------------------------------------

def test_bridgewater_says_dalio_no_longer_controls_it():
    """수치로는 유도할 수 없는 사실이라 유일하게 문장으로 들고 있는 것이다.

    달리오는 2022년 9월 의결권을 이사회에 넘기고 공동 CIO에서 물러났다. 그
    신고를 "달리오의 포트폴리오"라고 부르면 틀린다.
    """
    bridgewater = next(m for m in us_managers.MANAGERS if m.slug == "bridgewater")

    assert bridgewater.person_note_ko and "2022" in bridgewater.person_note_ko
    assert bridgewater.person_note_en and "2022" in bridgewater.person_note_en
    # 다른 신고자에는 붙이지 않는다 — 근거 없는 주석은 없느니만 못하다.
    assert [m.slug for m in us_managers.MANAGERS if m.person_note_ko] == ["bridgewater"]


def test_every_manager_has_a_distinct_cik():
    ciks = [m.cik for m in us_managers.MANAGERS]
    assert len(set(ciks)) == len(ciks)
    assert all(len(cik) == 10 and cik.isdigit() for cik in ciks)


# --- 6. 게이트 -------------------------------------------------------------

def test_the_route_fails_closed_when_the_lane_is_off():
    """EDGAR가 꺼져 있으면 만들어 보여주지 않고 닫는다."""
    response = client.get("/api/us/managers")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] in {"us_managers_disabled", "us_managers_not_configured"}


# --- 7. 배포되면 실제로 보이는가 ---------------------------------------------

def _static(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "app" / "static" / name).read_text(encoding="utf-8")


def test_the_page_carries_the_section_the_renderer_looks_for():
    us_html = _static("us.html")
    for node_id in ('id="us-managers"', 'id="usm-body"', 'id="usm-footer"'):
        assert node_id in us_html, f"{node_id}가 us.html에 없다"


def test_the_script_fetches_and_stores_and_renders():
    """`state` 대입을 빠뜨려 화면이 조용히 비었던 적이 있다(국민연금, 같은 날)."""
    monitor = _static("monitor.js")

    assert 'usManagers: ["us"]' in monitor, "PAGE_FETCHES에 없다"
    assert '"/api/us/managers", "usManagers"' in monitor
    assert "state.usManagers = usManagers;" in monitor, "state에 얹는 줄이 없다"
    assert "renderUsManagers();" in monitor, "렌더러를 부르는 곳이 없다"


def test_the_donut_geometry_is_shared_with_the_pension_chart():
    """두 벌로 두면 반드시 어긋난다 — 한쪽만 고치고 다른 쪽을 잊는다."""
    monitor = _static("monitor.js")

    assert monitor.count("function donutSvg(") == 1
    assert monitor.count("donutSvg(slices, {") == 2, "두 화면이 같은 함수를 쓰지 않는다"


@pytest.mark.parametrize("key", [
    "usm.title", "usm.copy", "usm.rest", "usm.restCount", "usm.centerLabel",
    "usm.period", "usm.lagged", "usm.options", "usm.indexed", "usm.manyNames",
    "usm.noMajority", "usm.filing", "usm.failed", "usm.andMore",
])
def test_both_languages_have_every_string(key: str):
    assert _static("monitor.js").count(f'"{key}":') == 2, f"{key}가 ko/en 양쪽에 있지 않다"


def test_the_section_copy_says_what_the_form_leaves_out():
    """13F가 자산 전부가 아니라는 말이 화면에 있어야 한다. 이 문장이 빠지면
    파이가 "그 사람의 재산"으로 읽힌다."""
    # 한국어는 마크업에도 있고(스크립트가 못 뜨는 경우의 바닥), 영어는 i18n에만 있다.
    assert "공매도" in _static("us.html")
    monitor = _static("monitor.js")
    assert "공매도" in monitor
    assert "short positions" in monitor
