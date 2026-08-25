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
from pathlib import Path

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

# --- 8. 인물 사진 -----------------------------------------------------------
#
# 사진은 라이선스가 붙은 남의 저작물이다. 숫자에 대해 지키는 규칙(출처가 값과
# 함께 다닌다)을 사진에도 그대로 적용한다.

def test_every_portrait_file_actually_ships():
    """payload가 가리키는 파일이 없으면 카드에 깨진 그림이 뜬다."""
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    for slug, portrait in us_managers.PORTRAITS.items():
        assert portrait.file.startswith("/static/portraits/"), slug
        path = static / portrait.file.removeprefix("/static/")
        assert path.exists(), f"{slug}: {path}가 없다"
        assert path.stat().st_size > 0


def test_every_portrait_names_its_author_and_licence():
    """CC BY 계열은 저작자와 라이선스를 밝혀야 쓸 수 있다."""
    for slug, portrait in us_managers.PORTRAITS.items():
        assert portrait.artist, slug
        assert portrait.licence, slug
        assert portrait.commons_file, slug
        assert portrait.source_url.startswith("https://commons.wikimedia.org/wiki/File:"), slug
        # 퍼블릭 도메인 말고는 라이선스 원문 링크가 있어야 한다.
        if portrait.licence.lower() != "public domain":
            assert portrait.licence_url.startswith("https://creativecommons.org/"), slug


def test_share_alike_is_flagged_where_it_applies():
    """우리는 원본을 자르고 줄였다 — BY-SA 사진의 가공본도 같은 라이선스다.

    이 값이 참인 항목이 하나라도 있으면 화면이 그 사실을 말해야 하고, 그
    문장은 `usm.photosCropped`가 들고 있다.
    """
    share_alike = [slug for slug, p in us_managers.PORTRAITS.items() if p.share_alike]
    assert share_alike == ["ark"], share_alike
    assert "BY-SA" in _static("monitor.js")


def test_no_portrait_for_people_without_a_free_photo():
    """드러켄밀러는 커먼즈에 사진이 없고, "Ken Fisher"로 나오는 사진은
    **동명이인**이다(Fisher House Foundation의 켄 피셔). 라이선스는 자유지만
    다른 사람이라 쓰면 카드에 엉뚱한 얼굴이 붙는다 — 이름만 보고 넣었으면
    아무도 눈치채지 못했을 종류의 오류다.
    """
    assert "duquesne" not in us_managers.PORTRAITS
    assert "fisher" not in us_managers.PORTRAITS
    assert us_managers._portrait_payload("fisher") is None


def test_the_card_payload_carries_the_portrait(card):
    """카드 조립에서 사진이 빠지면 화면은 전원 이니셜이 된다."""
    assert card["portrait"] is not None
    assert card["portrait"]["file"] == "/static/portraits/buffett.webp"


def test_the_page_falls_back_to_initials():
    """사진 없는 사람 자리가 비면 격자가 어긋난다."""
    monitor = _static("monitor.js")
    assert "is-initials" in monitor
    assert "usm-portrait" in monitor


def test_photos_are_self_hosted_not_hotlinked():
    """핫링크하면 읽는 사람의 브라우저가 위키미디어를 때린다 — 쿠키를 심지
    않는다는 방침과 결이 다르다."""
    for portrait in us_managers.PORTRAITS.values():
        assert "wikimedia.org" not in portrait.file
        assert portrait.file.startswith("/static/")


def test_the_fetch_script_is_not_imported_by_the_app():
    """Pillow는 `requirements.txt`에 없다. 앱이나 테스트가 이 스크립트를
    import하면 CI 수집 단계에서 배포가 막힌다(2026-08-21에 겪었다)."""
    root = Path(__file__).resolve().parents[1]
    here = Path(__file__).resolve()
    needle = "PIL"  # 이 파일 자신이 문자열로 담고 있으므로 아래에서 자신은 건너뛴다.
    for folder in ("app", "tests"):
        for path in (root / folder).rglob("*.py"):
            if path.resolve() == here:
                continue
            text = path.read_text(encoding="utf-8")
            assert "fetch_portraits" not in text, path
            assert f"from {needle}" not in text, path
            assert f"import {needle}" not in text, path

def test_portraits_are_served_as_images_not_as_text():
    """`StaticFiles`는 mimetypes 표에 기대고 그 표는 OS마다 다르다.

    webp를 모르는 환경에서는 사진이 `text/plain; charset=utf-8`로 나간다.
    폰트 때(`test_woff2_is_served_as_a_font_not_as_text`)와 달리 **브라우저가
    스니핑도 안 해 준다** — 실측(2026-08-25) 결과 카드의 얼굴이 통째로 안
    그려졌고 `naturalWidth`가 0이었다. 파일은 멀쩡한 `RIFF....WEBP`였다.

    테스트로는 잡히지 않아 눈으로 보다가 나온 종류라, 여기 묶어 둔다.
    """
    for portrait in us_managers.PORTRAITS.values():
        response = client.get(portrait.file)
        assert response.status_code == 200, portrait.file
        assert response.headers["content-type"] == "image/webp", portrait.file
        assert response.content[:4] == b"RIFF" and response.content[8:12] == b"WEBP"

# --- 9. 배포해도 화면이 안 바뀌는 사고 ---------------------------------------

def test_the_payload_declares_its_shape():
    """배치가 채우는 lane은 코드가 배포돼도 화면이 안 바뀐다 — 저장된 blob이
    옛 모양 그대로이기 때문이다.

    인물 사진을 붙인 날 실제로 그랬다(2026-08-25): 배포는 성공했고 코드도
    맞았는데 라이브는 **전원 이니셜**이었다. TTL이 24시간이라 그냥 뒀으면
    하루 동안 그 상태였을 것이다.
    """
    assert isinstance(us_managers.SCHEMA, int)
    source = (Path(__file__).resolve().parents[1] / "app" / "us_managers.py").read_text(encoding="utf-8")
    assert '"schema": SCHEMA' in source, "payload가 자기 모양을 밝히지 않는다"


def test_ingest_rebuilds_when_the_shape_changed(monkeypatch):
    """신선한 것만으로는 건너뛰면 안 된다 — 모양이 같아야 건너뛴다.

    캐시 키를 올리는 방법도 있지만 그러면 새 키에 blob이 없어 다음 수집까지
    503이 된다. 고치려다 더 오래 비우는 셈이라 이 길을 골랐다.
    """
    from app import ingest

    monkeypatch.setattr(ingest.config, "SEC_EDGAR_ENABLED", True)
    monkeypatch.setattr(ingest.config, "SEC_EDGAR_USER_AGENT", "test <t@example.com>")

    calls: list[bool] = []
    monkeypatch.setattr(ingest.us_managers, "refresh", lambda: calls.append(True) or {"managers": 6})

    # 옛 모양이 저장돼 있으면 TTL이 남아 있어도 다시 걷는다.
    monkeypatch.setattr(ingest.store, "load_report", lambda *a, **k: {"schema": None, "managers": []})
    assert ingest.refresh_us_managers() == {"managers": 6}
    assert calls == [True]

    # 같은 모양이면 건너뛴다.
    calls.clear()
    monkeypatch.setattr(
        ingest.store, "load_report",
        lambda *a, **k: {"schema": us_managers.SCHEMA, "managers": []},
    )
    assert ingest.refresh_us_managers() == {"skipped": "fresh"}
    assert calls == []

# --- 10. 분기 간 변화 --------------------------------------------------------
#
# 이 기능은 함정 위에 지어졌다. 실측(2026-08-25)으로 확인한 것만 묶는다.

def _pf(holdings, period):
    return _portfolio(holdings, period=period)


def _h(issuer, cusip, value, shares):
    return ManagerHolding(issuer=issuer, cusip=cusip, value_usd=value,
                          shares=shares, is_option=False)


def test_a_renamed_issuer_is_not_a_trade():
    """이 검사가 이 기능의 존재 이유다.

    버크셔가 `BANK AMERICA CORP`를 `BANK OF AMER CORP`로 고쳐 적었다. 이름으로
    맞추면 **275억 달러어치를 전량 매도하고 같은 분기에 새로 산 것**으로 보인다
    (실측 2026-08-25). CUSIP은 표기 변경을 타지 않는다.
    """
    prev = _pf([_h("BANK AMERICA CORP", "060505104", 25_039e6, 1000)], dt.date(2026, 3, 31))
    cur = _pf([_h("BANK OF AMER CORP", "060505104", 27_544e6, 1000)], dt.date(2026, 6, 30))

    changes = us_managers._changes(cur, prev)

    assert changes["counts"]["added"] == 0, "이름이 바뀐 것을 신규로 셌다"
    assert changes["counts"]["dropped"] == 0, "이름이 바뀐 것을 청산으로 셌다"
    assert changes["counts"]["unchanged"] == 1


def test_a_price_move_alone_is_not_a_change():
    """평가액이 아니라 **주식수**로 잰다."""
    prev = _pf([_h("APPLE INC", "037833100", 100e6, 500)], dt.date(2026, 3, 31))
    cur = _pf([_h("APPLE INC", "037833100", 140e6, 500)], dt.date(2026, 6, 30))

    counts = us_managers._changes(cur, prev)["counts"]

    assert counts["increased"] == 0 and counts["decreased"] == 0
    assert counts["unchanged"] == 1


def test_new_and_dropped_are_found_by_cusip():
    prev = _pf([_h("OLD CO", "111111111", 90e6, 10)], dt.date(2026, 3, 31))
    cur = _pf([_h("NEW CO", "222222222", 50e6, 20)], dt.date(2026, 6, 30))

    changes = us_managers._changes(cur, prev)

    assert [row["issuer"] for row in changes["added"]] == ["NEW CO"]
    assert [row["issuer"] for row in changes["dropped"]] == ["OLD CO"]
    assert changes["counts"] == {"added": 1, "dropped": 1, "increased": 0,
                                 "decreased": 0, "unchanged": 0}


def test_share_moves_are_counted_in_both_directions():
    prev = _pf([_h("UP", "1", 10e6, 100), _h("DOWN", "2", 10e6, 100)], dt.date(2026, 3, 31))
    cur = _pf([_h("UP", "1", 10e6, 150), _h("DOWN", "2", 10e6, 40)], dt.date(2026, 6, 30))

    counts = us_managers._changes(cur, prev)["counts"]

    assert counts["increased"] == 1
    assert counts["decreased"] == 1


def test_the_period_pair_travels_with_the_change():
    """신고자마다 최신 분기가 다르다 — 퍼싱은 한 분기 밀려 있다(실측 147일).
    "이번 분기"라고만 쓰면 카드마다 다른 것을 가리킨다."""
    prev = _pf([_h("A", "1", 1e6, 1)], dt.date(2025, 12, 31))
    cur = _pf([_h("A", "1", 1e6, 1)], dt.date(2026, 3, 31))

    changes = us_managers._changes(cur, prev)

    assert changes["from_period"] == "2025-12-31"
    assert changes["to_period"] == "2026-03-31"


def test_only_a_few_names_are_listed():
    """브리지워터는 한 분기에 200종목이 드나든다(실측 신규 214·빠짐 210).
    이름을 다 적으면 카드가 목록이 된다 — 개수로 말하고 큰 것만 적는다."""
    prev = _pf([_h("KEEP", "0", 1e6, 1)], dt.date(2026, 3, 31))
    cur = _pf(
        [_h("KEEP", "0", 1e6, 1)]
        + [_h(f"N{i}", str(i + 1), (100 - i) * 1e6, 1) for i in range(40)],
        dt.date(2026, 6, 30),
    )

    changes = us_managers._changes(cur, prev)

    assert changes["counts"]["added"] == 40
    assert len(changes["added"]) == us_managers.NAMED_CHANGES
    # 큰 것부터 적는다.
    assert changes["added"][0]["issuer"] == "N0"


def test_no_previous_quarter_means_no_change_block():
    """직전 분기를 못 읽어도 현재 구성까지 잃을 이유는 없다."""
    cur = _pf([_h("A", "1", 1e6, 1)], dt.date(2026, 6, 30))

    assert us_managers._changes(cur, None) is None


def test_the_screen_does_not_call_it_a_sale():
    """목록에서 빠진 것이 곧 매도는 아니다 — 비공개 신청이면 보유한 채로 빠진다.

    그래서 화면 문구가 `청산`이나 `매도`가 아니어야 한다.
    """
    monitor = _static("monitor.js")
    assert '"usm.dropped": "목록에서 빠짐"' in monitor
    assert '"usm.dropped": "Left the list"' in monitor
    # 주의문이 세 가지 사정을 다 말해야 한다.
    assert "비공개" in monitor
    assert "분할" in monitor
    assert "주식수" in monitor


def test_the_schema_was_bumped_for_the_new_shape():
    """payload에 `changes`가 생겼다 — 모양이 바뀌면 번호를 올려야 배치가
    저장된 옛 blob을 스스로 다시 걷는다."""
    assert us_managers.SCHEMA >= 2
