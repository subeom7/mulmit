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


def test_more_than_five_stocks_split_into_separate_requests(open_lane, roster):
    """다섯을 넘으면 요청이 갈라진다 — 상류가 주제어 5개까지만 받는다."""
    provider = FakeProvider({name: _flat(50.0) for name in roster.values()})
    payload = kr_search_interest.build(list(roster), today=dt.date(2026, 8, 23), provider=provider)
    assert len(provider.calls) == 2
    assert [len(call) for call in provider.calls] == [5, 1]
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
