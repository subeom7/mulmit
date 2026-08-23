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
    """경로도 헤더도 구 개발자센터와 다르다 — 실측으로 확정했다(2026-08-24).

    게이트웨이는 키가 없어도 **401(경로 있음) 대 404(경로 없음)**로 답이 갈려서,
    자격증명을 만지지 않고 확인할 수 있었다:

        POST naveropenapi.apigw.ntruss.com/datalab/v1/search → 401  ← 여기 있다
        POST naverapihub.apigw.ntruss.com/datalab/v1/search  → 404  ← 검색 API가 간 곳

    헤더 이름도 같은 방법으로 갈랐다. 구 헤더를 보내면 "Authentication information
    are missing"(못 봤다), NCP 헤더를 보내면 "Invalid authentication information"
    (읽고 거절했다)이다.

    이 갈림은 권리 판정과 겹친다 — 데이터랩은 검색 특약이 붙은 API HUB 약관이
    아니라 `AI·Naver API 서비스 이용약관`을 따른다(등록부 §3.29·§6.7).
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

    assert captured["url"] == "https://naveropenapi.apigw.ntruss.com/datalab/v1/search"
    headers = captured["headers"]
    assert headers["X-NCP-APIGW-API-KEY-ID"] == "id"
    assert headers["X-NCP-APIGW-API-KEY"] == "secret"
    assert "X-Naver-Client-Id" not in headers, "구 개발자센터 헤더로는 게이트웨이가 못 알아본다"
