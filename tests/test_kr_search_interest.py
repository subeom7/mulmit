"""종목 검색 관심도 lane — 상류의 함정 하나가 이 lane의 설계 전부다.

데이터랩은 **요청된 기간 중 최댓값을 100**으로 두고 나머지를 상대값으로 준다.
절댓값은 주지 않는다. 그래서 종목이 다섯을 넘어 요청이 갈라지면, 갈라진 두
요청의 100은 **서로 다른 것을 뜻한다**. 이걸 모르고 원값을 나란히 놓으면 화면이
조용히 거짓말을 한다 — 에러도 경고도 없이.

그래서 여기서 확인하는 것은 대체로 "무엇을 하지 않는가"다: 요청 사이의 원값을
섞지 않는지, 줄 세우기가 자기 대비 지표로만 이뤄지는지, 저장하지 않는지.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from app import config, kr_search_interest, store
from app.providers import naver_datalab
from app.providers.base import DataUnavailable


class FakeProvider:
    """호출을 그대로 기록한다 — 몇 번 갈라졌는지가 이 lane의 핵심이라서."""

    def __init__(self, series_by_name: dict[str, list[float]]):
        self.series_by_name = series_by_name
        self.calls: list[list[str]] = []

    def fetch_trend(self, groups, *, start, end, time_unit="date"):
        names = [name for name, _keywords in groups]
        assert len(names) <= naver_datalab.MAX_GROUPS
        self.calls.append(names)
        span = (end - start).days + 1
        out = []
        for name in names:
            values = self.series_by_name.get(name)
            if values is None:
                continue
            points = [
                {"period": (start + dt.timedelta(days=i)).isoformat(), "ratio": value}
                for i, value in enumerate(values[:span])
            ]
            out.append({"title": name, "keywords": [name], "series": points})
        return {"fetched_at": "2026-08-23T00:00:00Z", "groups": out}


@pytest.fixture
def open_lane(monkeypatch):
    monkeypatch.setattr(config, "NAVER_DATALAB_ENABLED", True)
    monkeypatch.setattr(config, "NAVER_DATALAB_CLIENT_ID", "id")
    monkeypatch.setattr(config, "NAVER_DATALAB_CLIENT_SECRET", "secret")


@pytest.fixture
def roster(monkeypatch):
    names = {
        "005930": "삼성전자",
        "000660": "SK하이닉스",
        "035420": "NAVER",
        "051910": "LG화학",
        "005380": "현대차",
        "207940": "삼성바이오로직스",
    }
    monkeypatch.setattr(
        store,
        "get_kr_listing",
        lambda code: (
            {"itms_nm": names[code], "mrkt_ctg": "KOSPI"} if code in names else None
        ),
    )
    return names


def _flat(value: float, days: int = 90) -> list[float]:
    return [value] * days


def _weekly(start: dt.date, weekday_value: float, weekend_value: float, days: int = 90) -> list[float]:
    """실제 검색 추이의 모양 — 주말이 평일의 한 조각이다.

    2026-08-24 실측: 삼성전자 평일 중앙값 55~64, 토 8.9, 일 7.5.
    """
    return [
        weekend_value if (start + dt.timedelta(days=i)).weekday() >= 5 else weekday_value
        for i in range(days)
    ]


def test_the_lane_stays_shut_without_credentials(monkeypatch, roster):
    """게이트만 켜고 키를 안 넣은 상태는 '데이터 없음'이 아니라 고장이다."""
    monkeypatch.setattr(config, "NAVER_DATALAB_ENABLED", True)
    monkeypatch.setattr(config, "NAVER_DATALAB_CLIENT_ID", "")
    monkeypatch.setattr(config, "NAVER_DATALAB_CLIENT_SECRET", "")
    with pytest.raises(kr_search_interest.KrSearchInterestDisabled):
        kr_search_interest.build(["005930"])


def test_every_request_carries_the_anchor(open_lane, roster):
    """상류는 주제어 5개까지 받는데, 그중 한 자리는 늘 앵커가 쓴다.

    앵커가 요청을 잇는 다리다. 같은 날 앵커 대비 비율은 그 요청의 정규화와
    무관하므로(분자·분모가 같은 요청에서 나온다), 요청이 갈려도 종목 간 수준을
    견줄 수 있다. 앵커를 빠뜨린 요청의 종목들은 수준을 잴 방법이 없다.
    """
    provider = FakeProvider({name: _flat(50.0) for name in roster.values()})
    payload = kr_search_interest.build(list(roster), today=dt.date(2026, 8, 23), provider=provider)
    assert len(provider.calls) == 2
    assert [len(call) for call in provider.calls] == [5, 2], "앵커 1 + 나머지 4가 한 요청의 상한"
    for call in provider.calls:
        assert call[0] == "삼성전자", "앵커는 모든 요청의 첫 자리에 있어야 한다"
    assert payload["count"] == 6


def test_each_stock_carries_the_batch_it_was_measured_in(open_lane, roster):
    """원값 비교는 같은 묶음 안에서만 성립한다 — 화면이 실수로 섞지 못하게 번호를 준다.

    이게 없으면 1번 묶음의 100과 2번 묶음의 100이 같은 크기처럼 보인다.
    """
    provider = FakeProvider({name: _flat(50.0) for name in roster.values()})
    payload = kr_search_interest.build(list(roster), today=dt.date(2026, 8, 23), provider=provider)
    batches = {stock["code"]: stock["batch"] for stock in payload["stocks"]}
    assert set(batches.values()) == {0, 1}, "묶음 번호가 없으면 섞였는지 알 수 없다"


def test_ranking_uses_self_relative_measures_not_raw_ratios(open_lane, roster):
    """줄 세우기는 자기 평소 대비로만 한다.

    A는 다른 묶음에서 원값이 훨씬 크지만 내내 평평하고, B는 원값이 작아도 끝에서
    치솟는다. 원값으로 세우면 A가 위에 서는데 그건 **다른 자로 잰 길이**다.
    """
    flat_high = _flat(100.0)
    spiking_low = _flat(5.0, 83) + [40.0] * 7
    provider = FakeProvider(
        {
            "삼성전자": flat_high,
            "SK하이닉스": flat_high,
            "NAVER": flat_high,
            "LG화학": flat_high,
            "현대차": flat_high,
            "삼성바이오로직스": spiking_low,  # 두 번째 묶음, 원값은 훨씬 작다
        }
    )
    payload = kr_search_interest.build(list(roster), today=dt.date(2026, 8, 23), provider=provider)
    top = payload["stocks"][0]
    assert top["code"] == "207940", "치솟은 쪽이 위여야 한다 — 원값이 아니라 자기 대비로 잰다"
    assert top["latest"] < payload["stocks"][-1]["latest"], "원값은 오히려 더 작다"


def test_a_failed_batch_does_not_invent_the_missing_stocks(open_lane, roster, monkeypatch):
    """한 묶음이 죽어도 나머지는 살리되, 빈 자리를 채우지는 않는다."""
    provider = FakeProvider({"삼성전자": _flat(50.0)})  # 나머지는 계열이 없다
    payload = kr_search_interest.build(
        ["005930", "000660"], today=dt.date(2026, 8, 23), provider=provider
    )
    assert [stock["code"] for stock in payload["stocks"]] == ["005930"]


def test_an_empty_watchlist_is_not_a_reason_to_walk_the_whole_roster(open_lane, roster):
    """워치리스트가 비면 닫는다. 3,000종목을 도는 것은 쿼틴가 아니라 뜻에서 틀린다."""
    with pytest.raises(DataUnavailable):
        kr_search_interest.build([], today=dt.date(2026, 8, 23), provider=FakeProvider({}))


def test_the_payload_says_it_is_not_a_volume_ranking(open_lane, roster):
    """절댓값이 없으므로 '가장 많이 검색된 종목'은 만들 수 없다 — 문구가 그걸 밝혀야 한다."""
    provider = FakeProvider({"삼성전자": _flat(50.0)})
    payload = kr_search_interest.build(["005930"], today=dt.date(2026, 8, 23), provider=provider)
    assert "검색량 순위가 아닙니다" in payload["basis_ko"]
    assert "not a search-volume ranking" in payload["basis_en"]
    assert payload["rights"]["stored"] is False


def test_a_stock_with_no_search_history_gets_no_multiple(open_lane, roster):
    """창 내내 검색이 없었으면 배수는 0으로 나누기다 — 숫자를 지어내지 않는다."""
    provider = FakeProvider({"삼성전자": _flat(0.0, 83) + [12.0] * 7})
    payload = kr_search_interest.build(["005930"], today=dt.date(2026, 8, 23), provider=provider)
    assert payload["stocks"][0]["vs_baseline"] is None


def test_the_request_stops_at_the_documented_limits():
    """상한을 넘기면 상류가 400을 준다. 여기서 먼저 걸러야 어느 종목이 빠졌는지 안다."""
    day = dt.date(2026, 8, 1)
    with pytest.raises(ValueError, match="주제어"):
        naver_datalab.build_request(
            [(str(i), ["a"]) for i in range(6)], start=day, end=day
        )
    with pytest.raises(ValueError, match="검색어"):
        naver_datalab.build_request(
            [("x", [f"w{i}" for i in range(21)])], start=day, end=day
        )
    with pytest.raises(ValueError, match="2016-01-01"):
        naver_datalab.build_request([("x", ["a"])], start=dt.date(2015, 12, 31), end=day)


def test_the_parser_drops_unreadable_rows_instead_of_guessing():
    raw = {
        "startDate": "2026-06-01",
        "endDate": "2026-06-03",
        "timeUnit": "date",
        "results": [
            {
                "title": "삼성전자",
                "keywords": ["삼성전자"],
                "data": [
                    {"period": "2026-06-01", "ratio": 10},
                    {"period": "2026-06-02", "ratio": "쓰레기"},
                    {"period": "", "ratio": 30},
                    {"period": "2026-06-03", "ratio": 40},
                ],
            }
        ],
    }
    parsed = naver_datalab.parse_trend(raw, fetched_at="2026-08-23T00:00:00Z")
    series = parsed["groups"][0]["series"]
    assert [point["period"] for point in series] == ["2026-06-01", "2026-06-03"]


def test_an_empty_result_is_an_error_not_an_empty_chart():
    with pytest.raises(DataUnavailable):
        naver_datalab.parse_trend({"results": []}, fetched_at="2026-08-23T00:00:00Z")


def test_the_request_goes_to_the_ncp_gateway_with_ncp_headers():
    """경로도 헤더도 구 개발자센터와 다르다. 여기까지 **두 번 틀렸다**.

        openapi.naver.com/v1/datalab/search              구 개발자센터
        naveropenapi.apigw.ntruss.com/datalab/v1/search  구 게이트웨이의 레거시 경로
        naverapihub.apigw.ntruss.com/search-trend/v1/search   ← 실제 (실측 200)

    두 번째가 함정이었다. 그 주소는 404가 아니라 **401 code=210 "A subscription to
    the API is required"** 를 돌려준다. 권한 얘기를 하니 "경로는 맞는데 구독만
    없다"로 읽힌다. 실제로는 API HUB 키에 그 구독이 없는 게 정상이었다 — 210은
    "여기가 맞다"가 아니라 "여기가 아니다"였다.

    경로를 41가지 조합으로 훑고도 못 찾았다. 접두어를 /datalab·/data-lab·/insight·
    /trend로 잡았는데 정답은 접두어 자체가 /search-trend였다. 추측으로 찾을 수 있는
    것이 아니었고, 공식 Dev guide가 답이었다. 그래서 여기 못 박아 둔다.
    """
    captured: dict[str, object] = {}

    def transport(url, body, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return {
            "startDate": "2026-08-01",
            "endDate": "2026-08-01",
            "timeUnit": "date",
            "results": [{"title": "x", "keywords": ["x"], "data": [{"period": "2026-08-01", "ratio": 1}]}],
        }

    provider = naver_datalab.DatalabProvider(
        client_id="id", client_secret="secret", transport=transport
    )
    provider.fetch_trend([("x", ["x"])], start=dt.date(2026, 8, 1), end=dt.date(2026, 8, 1))

    assert captured["url"] == "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
    headers = captured["headers"]
    assert headers["X-NCP-APIGW-API-KEY-ID"] == "id"
    assert headers["X-NCP-APIGW-API-KEY"] == "secret"
    assert "X-Naver-Client-Id" not in headers, "구 개발자센터 헤더로는 게이트웨이가 못 알아본다"


def test_a_weekend_is_not_a_collapse(open_lane, roster):
    """요일을 섞은 기준선에 오늘을 견주면 주말마다 급락이 찍힌다.

    2026-08-24 실측이 이 테스트의 근거다 — 삼성전자 평일 중앙값 55~64에 토 8.9,
    일 7.5. 주말이 평일의 12~14%다. 요일을 섞으면 토요일에 x0.16이 나오는데
    그건 관심이 식은 게 아니라 토요일이라서다. 같은 요일끼리 견주면 x1.00이다.

    이 고장은 에러를 내지 않는다. 매주 조용히 거짓말을 할 뿐이다.
    """
    end = dt.date(2026, 8, 22)  # 토요일
    start = end - dt.timedelta(days=89)
    provider = FakeProvider({"삼성전자": _weekly(start, 60.0, 9.0)})
    payload = kr_search_interest.build(
        ["005930"], today=end + dt.timedelta(days=1), provider=provider
    )
    stock = payload["stocks"][0]
    assert stock["compared_to"]["weekday"] == 5, "마지막 점은 토요일이다"
    assert stock["vs_baseline"] == 1.0, (
        f"토요일을 토요일들과 견주면 평범해야 한다 (얻은 값 {stock['vs_baseline']})"
    )
    assert stock["baseline"] == 9.0, "기준선은 평일이 섞인 중앙값이 아니라 토요일 중앙값이다"


def test_a_real_spike_still_shows_through_the_weekly_cycle(open_lane, roster):
    """주기를 지운 것이지 신호를 지운 것이 아니다 — 진짜 급등은 그대로 보여야 한다."""
    end = dt.date(2026, 8, 22)
    start = end - dt.timedelta(days=89)
    series = _weekly(start, 60.0, 9.0)
    series[-1] = 36.0  # 토요일인데 평소 토요일의 네 배
    provider = FakeProvider({"삼성전자": series})
    payload = kr_search_interest.build(
        ["005930"], today=end + dt.timedelta(days=1), provider=provider
    )
    stock = payload["stocks"][0]
    assert stock["vs_baseline"] == 4.0
    assert stock["percentile"] == 100.0


def test_too_few_samples_of_that_weekday_means_no_number(open_lane, roster):
    """표본이 얇으면 중앙값이 흔들린다 — 흔들리는 배수를 내느니 안 낸다."""
    end = dt.date(2026, 8, 22)
    start = end - dt.timedelta(days=13)  # 두 주 = 토요일 표본 1개
    provider = FakeProvider({"삼성전자": _weekly(start, 60.0, 9.0, days=14)})
    payload = kr_search_interest.build(
        ["005930"], today=end + dt.timedelta(days=1), provider=provider
    )
    stock = payload["stocks"][0]
    assert stock["vs_baseline"] is None
    assert stock["baseline"] is None
    assert stock["compared_to"]["samples"] < kr_search_interest.MIN_WEEKDAY_SAMPLES


def test_the_screen_never_puts_raw_ratios_side_by_side():
    """표에 세우는 숫자는 자기 대비 지표뿐이어야 한다.

    데이터랩은 요청 기간의 최댓값을 100으로 둔다. 2026-08-24 실측에서 삼성전자의
    최대가 100이고 LG에너지솔루션의 최대도 100이었다 — 서로 다른 요청이라 **다른
    자로 잰 100**이다. 그 원값을 한 열에 나란히 세우면 화면이 조용히 거짓말을 한다.

    원값은 추이선의 모양으로만 쓴다(모양은 계열 안에서 닫혀 있어 안전하다).
    """
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "app" / "static"
    source = (static / "monitor.js").read_text(encoding="utf-8")
    start = source.index("function renderKrSearchInterest()")
    block = source[start : source.index("function renderKrEtf()", start)]

    assert "vs_baseline" in block and "percentile" in block, "비교 열은 자기 대비 지표다"
    assert "stock.latest" not in block and "stock.peak" not in block, (
        "원값(latest·peak)을 표에 세우면 요청이 다른 종목끼리 다른 자로 잰 값이 나란히 선다"
    )
    assert "mulmitSparkline" in block, "추이선은 홈 타일·야간 카드와 같은 함수를 써야 창 규칙이 갈리지 않는다"


def test_the_section_says_what_it_is_not():
    """절댓값이 없으므로 검색량 순위처럼 읽히면 안 된다 — 화면이 그걸 밝혀야 한다."""
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "kr.html").read_text(encoding="utf-8")
    assert 'id="kr-search-interest"' in html
    assert "ksi.badgeNotRank" in html, "검색량 순위가 아니라는 배지가 있어야 한다"
    assert "ksi.badgeWeekday" in html, "같은 요일끼리 견준다는 사실이 화면에 있어야 한다"


def test_the_span_label_is_written_once_not_once_per_row():
    """여덟 줄에 "30일"을 여덟 번 쓰면 그건 정보가 아니라 소음이다.

    카드에서는 카드마다 하나였으니 맞았다. 표에서는 같은 말이 세로로 반복되면서
    추이 열의 폭을 먹는다 — 기간은 열 이름에 한 번만 적는다.

    다만 어느 줄의 창이 짧으면(계열이 덜 모인 종목) 그 줄에만 적는다. 같은 열의
    선들이 서로 다른 기간이면 모양을 나란히 읽을 수 없기 때문이다.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "static" / "monitor.js").read_text(
        encoding="utf-8"
    )
    start = source.index("function renderKrSearchInterest()")
    block = source[start : source.index("function renderKrEtf()", start)]
    assert "ksi-trend-head" in block, "기간은 열 이름에 붙는다"
    assert "spark.label !== spanLabel" in block, (
        "창이 다른 줄에만 따로 적어야 한다 — 전부 지우면 다른 기간의 선이 같은 기간처럼 보인다"
    )


def test_the_not_a_ranking_badge_shows_in_beginner_mode_too():
    """정렬된 표를 순위로 오해하는 것은 초보자다 — 전문가 모드에 숨길 것이 아니다."""
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "kr.html").read_text(
        encoding="utf-8"
    )
    line = next(row for row in html.splitlines() if "ksi.badgeNotRank" in row)
    assert "pro-only" not in line, "이 배지는 두 모드 모두에서 보여야 한다"


def test_an_ambiguous_company_name_can_be_given_a_narrower_keyword(open_lane, roster, monkeypatch):
    """`NAVER`를 검색한 사람 대부분은 주식을 보러 온 게 아니다.

    회사 이름이 회사만 가리키지 않는 종목이 있다. 그런 종목은 검색어를 좁혀야
    측정하는 것이 실제로 "이 주식에 대한 관심"이 된다. 화면에 서는 이름은 그대로
    로스터의 회사명이다 — 검색어를 좁혔다고 표에 `NAVER 주가`라고 쓰면 안 된다.
    """
    monkeypatch.setattr(config, "NAVER_DATALAB_WATCHLIST", "005930,035420=NAVER 주가")
    assert kr_search_interest.watchlist() == [("005930", None), ("035420", "NAVER 주가")]

    provider = FakeProvider({"삼성전자": _flat(50.0), "NAVER 주가": _flat(20.0)})
    payload = kr_search_interest.build(today=dt.date(2026, 8, 23), provider=provider)

    assert provider.calls == [["삼성전자", "NAVER 주가"]], "상류에는 좁힌 검색어로 물어본다"
    names = {stock["code"]: stock["name"] for stock in payload["stocks"]}
    assert names["035420"] == "NAVER", "화면에는 회사명이 선다"


def test_a_watchlist_entry_without_an_override_still_uses_the_company_name(open_lane, roster, monkeypatch):
    monkeypatch.setattr(config, "NAVER_DATALAB_WATCHLIST", "005930")
    assert kr_search_interest.watchlist() == [("005930", None)]
    provider = FakeProvider({"삼성전자": _flat(50.0)})
    payload = kr_search_interest.build(today=dt.date(2026, 8, 23), provider=provider)
    assert provider.calls == [["삼성전자"]]
    assert payload["stocks"][0]["name"] == "삼성전자"


def test_the_level_is_measured_against_the_anchor_not_the_request(open_lane, roster):
    """수준은 요청을 가로질러 비교할 수 있어야 한다.

    데이터랩은 요청마다 최댓값을 100으로 둔다. 그래서 두 요청의 원값은 다른 자로
    잰 길이다. 앵커를 두 요청에 함께 넣으면 그 문제가 사라진다 — 같은 날 앵커
    대비 비율은 분자와 분모가 같은 요청에서 나오므로 정규화가 약분된다.

    여기서는 두 번째 묶음의 종목이 앵커의 절반이다. 요청이 갈렸어도 수준은
    50이어야 한다.
    """
    provider = FakeProvider(
        {
            "삼성전자": _flat(80.0),
            "SK하이닉스": _flat(40.0),
            "NAVER": _flat(20.0),
            "LG화학": _flat(10.0),
            "현대차": _flat(8.0),
            # 두 번째 묶음. 상류는 이 요청에서 앵커를 100으로 정규화해서 준다고
            # 가정해도(FakeProvider는 원값을 그대로 주지만) 비율은 같아야 한다.
            "삼성바이오로직스": _flat(40.0),
        }
    )
    payload = kr_search_interest.build(list(roster), today=dt.date(2026, 8, 23), provider=provider)
    levels = {stock["code"]: stock["level"] for stock in payload["stocks"]}
    assert levels["005930"] == 100.0, "앵커가 기준이다"
    assert levels["000660"] == 50.0
    assert levels["207940"] == 50.0, "다른 요청에 있어도 같은 자로 잰 값이어야 한다"


def test_rank_change_is_unknown_rather_than_zero_when_yesterday_is_missing(open_lane, roster):
    """어제 순위를 모르면 변동도 모른다 — 0으로 두면 "제자리"라는 거짓이 된다."""
    provider = FakeProvider({"삼성전자": [50.0], "SK하이닉스": [25.0]})
    payload = kr_search_interest.build(
        ["005930", "000660"], today=dt.date(2026, 8, 23), provider=provider
    )
    for stock in payload["stocks"]:
        assert stock["level_rank"] is not None
        assert stock["level_rank_change"] is None


def test_rank_change_reports_real_movement(open_lane, roster):
    """어제 3등이던 종목이 오늘 1등이면 ▲2다."""
    # 마지막 날에 순서가 뒤집힌다.
    provider = FakeProvider(
        {
            "삼성전자": _flat(100.0),
            "SK하이닉스": _flat(10.0, 89) + [1.0],
            "NAVER": _flat(5.0, 89) + [50.0],
        }
    )
    payload = kr_search_interest.build(
        ["005930", "000660", "035420"], today=dt.date(2026, 8, 23), provider=provider
    )
    by_code = {stock["code"]: stock for stock in payload["stocks"]}
    assert by_code["035420"]["level_rank"] == 2
    assert by_code["035420"]["level_rank_change"] == 1, "3등 → 2등이면 ▲1"
    assert by_code["000660"]["level_rank_change"] == -1


def test_the_two_sort_modes_ask_different_questions():
    """정렬 토글은 값을 바꾸지 않는다 — 순서만 바꾼다.

    "누가 평소보다 튀었나"(vs_baseline)와 "누가 더 많이 검색되나"(level)는 다른
    질문이고, 답도 다르게 나온다. 어느 쪽을 보고 있는지 화면이 밝혀야 한다.
    """
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "app" / "static"
    source = (static / "monitor.js").read_text(encoding="utf-8")
    start = source.index("function renderKrSearchInterest()")
    block = source[start : source.index("function renderKrEtf()", start)]
    assert 'state.ksiSort === "level"' in block
    assert "b.level" in block and "b.vs_baseline" in block, "두 정렬 기준이 모두 있어야 한다"

    html = (static / "kr.html").read_text(encoding="utf-8")
    assert 'id="ksi-sort"' in html
    assert "ksi.sortSpike" in html and "ksi.sortLevel" in html


def test_the_rank_move_badge_does_not_pretend_to_be_realtime():
    """데이터랩은 일별이고 마지막 점이 하루~이틀 전이다.

    실측(2026-08-24): endDate를 오늘로 줘도 마지막 점이 8/22였다. 순위 변동은
    전날 대비이며 하루에 한 번만 바뀐다 — 초 단위로 깜빡이는 장치를 붙이면
    없는 움직임을 그리는 것이다.
    """
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "app" / "static" / "console.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".ksi-rank")
    block = css[start : start + 1200]
    assert "animation" not in block and "@keyframes" not in block, (
        "순위 변동에 반복 애니메이션을 붙이지 말 것 — 데이터는 하루에 한 번 바뀐다"
    )


def test_a_moved_row_is_marked_neutrally_not_in_the_price_colours():
    """줄의 색과 숫자의 색이 다른 주장을 하면 독자는 어느 쪽인지 알 수 없다.

    라이브에서 잡혔다(2026-08-24): 카카오가 ×2.02 — 평소의 두 배, 표에서 가장
    강한 신호 — 인데 줄 전체가 빨갰다. 수준 순위가 한 칸 내려갔다는 뜻이었지만
    이 사이트에서 빨강은 "내렸다"이다. 하필 가장 눈에 띄는 종목에서 부딪혔다.

    방향은 ▲▼ 배지가 말한다. 줄은 "여기가 움직였다"만 말한다.
    """
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "app" / "static" / "console.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".kridx-table tr.rank-up")
    block = css[start : start + 400]
    assert "var(--up)" not in block and "var(--down)" not in block, (
        "옮긴 줄에 등락 색을 쓰지 말 것 — 숫자의 색과 다른 주장을 하게 된다"
    )


def test_one_stock_is_measured_against_the_anchor(open_lane, roster):
    """앵커 없이 혼자 부르면 그 종목이 자기 요청의 최댓값이라 언제나 100이다.

    그건 아무 뜻도 없는 숫자다. 종목 화면에서 부르는 경로는 앵커를 함께 넣어
    한 번에 묻는다 — 그래야 이 화면의 수준이 `/kr` 표의 값과 같은 자로 잰
    것이 된다.
    """
    provider = FakeProvider({"삼성전자": _flat(80.0), "SK하이닉스": _flat(20.0)})
    payload = kr_search_interest.build_for("000660", today=dt.date(2026, 8, 23), provider=provider)

    assert provider.calls == [["삼성전자", "SK하이닉스"]], "상류 호출은 한 번, 앵커와 함께"
    assert payload["stock"]["code"] == "000660"
    assert payload["stock"]["level"] == 25.0, "앵커=100 기준으로 잰 값이어야 한다"
    assert payload["anchor"]["code"] == "005930"


def test_asking_for_the_anchor_itself_does_not_ask_twice(open_lane, roster):
    provider = FakeProvider({"삼성전자": _flat(80.0)})
    payload = kr_search_interest.build_for("005930", today=dt.date(2026, 8, 23), provider=provider)
    assert provider.calls == [["삼성전자"]]
    assert payload["stock"]["level"] == 100.0


def test_the_stock_screen_uses_the_shared_sparkline() -> None:
    """창을 자르는 규칙이 화면마다 갈리면 같은 그림이 다른 뜻이 된다."""
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "app" / "static"
    source = (static / "stock.html").read_text(encoding="utf-8")
    assert "window.mulmitSparkline" in source
    assert "/static/console.js" in source, (
        "그 함수는 console.js에 있다 — 안 실으면 조용히 undefined가 되어 선이 안 그려진다"
    )


def test_the_stock_page_sparkline_keeps_its_aspect_ratio() -> None:
    """폭을 100%로 늘리면 선이 찌그러져 세로 움직임이 작아 보인다.

    2026-08-24 실측: viewBox가 240×46(5.2:1)인데 그려진 크기가 1288×46(28:1)이었다.
    그리는 함수가 `preserveAspectRatio="none"`이라 그대로 늘어난다 — 값이 아니라
    **모양**이 거짓말을 하는 종류이고, 검색 관심도는 주중·주말 진폭이 큰 계열이라
    하필 그 진폭이 뭉개진다. 사이트의 다른 추이선은 전부 5.2를 지킨다.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "static" / "stock.html").read_text(
        encoding="utf-8"
    )
    match = re.search(r"\.ksi-spark svg\s*\{([^}]*)\}", source)
    assert match, ".ksi-spark svg 규칙이 있어야 한다"
    assert "width: 100%" not in match.group(1), "폭을 늘리면 비율이 깨진다"
