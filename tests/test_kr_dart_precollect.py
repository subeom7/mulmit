"""DART 재무·소유보고를 배치가 미리 모은다 (2026-08-26).

왜 생겼나. `/stock/{국내코드}`의 두 블록(연간 재무제표·임원 소유보고)은
2026-08-26까지 **사람이 그 페이지를 열어야만** 채워졌다. 요청 경로에서 DART를
동기로 부르는 구조였기 때문이다. 그게 콜드 응답 3.4~5.9초의 정체였고, 크롤러
트래픽이 그대로 DART 호출로 번역되고 있었다.

그 경로를 막고 나니(#267) 채우는 유일한 경로가 같이 사라졌다. 실측:

    FSC 시세 있는 종목   320
    DART 재무 캐시        62   ← 사람·크롤러가 연 만큼만
    DART 소유보고 캐시     64

그래서 종가 사전수집과 같은 모양으로 배치가 모은다. 이 파일이 지키는 것:

1. 사이트맵이 광고하는 집합만 채운다 — 광고한 것과 크롤러가 받는 것이 어긋나면
   안 된다.
2. 이미 있는 것은 다시 부르지 않는다 — 주기당 예산이 거기서 다 나간다.
3. 한도에 닿으면 멈춘다. 다른 수집이 같은 한도를 나눠 쓴다.
4. 한 종목의 실패가 나머지를 막지 않는다.
"""

from __future__ import annotations

import pytest

from app import config, ingest, kr_fundamentals, kr_insider, store
from app.providers import RateLimited


@pytest.fixture
def dart_open(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "test-key")
    monkeypatch.setattr(config, "KR_PRECOLLECT_TOP", 50)
    return db


def _seed(codes: list[str], *, listings_only: list[str] | None = None) -> None:
    """시총 로스터와 종가 계열을 함께 심는다 — 둘 다 있어야 대상이 된다."""
    import datetime as dt

    from app.kr_stocks import stock_series_spec

    rows = [
        {"srtn_cd": code, "itms_nm": f"종목{code}", "mrkt_ctg": "KOSPI",
         "clpr": 1.0, "flt_rt": 0.0, "mrkt_tot_amt": float(10_000_000_000 - index)}
        for index, code in enumerate(codes + list(listings_only or []))
    ]
    store.save_kr_listings(rows, "20260825")
    for code in codes:
        spec = stock_series_spec(code, f"종목{code}")
        store.save_economic_series(
            spec.series_key, provider_id="fsc", provider_series_id=code,
            metadata_fields={"title": f"종목{code}", "units": "KRW", "units_short": "원",
                             "frequency": "Daily", "frequency_short": "D"},
            observations=[(dt.date(2026, 8, 24), 1.0), (dt.date(2026, 8, 25), 1.1)],
            publisher="금융위원회", publisher_url="https://www.fsc.go.kr/",
            series_url="https://www.data.go.kr/data/15094808/openapi.do",
            rights_status="approved",
        )


def test_it_only_fills_what_the_sitemap_advertises(dart_open, monkeypatch) -> None:
    """사이트맵은 종가가 있는 종목만 올린다. 사전수집도 같은 집합이어야 한다."""
    # 000333은 로스터에만 있고 종가 계열이 없다 — 사이트맵에 없으므로 대상 아니다.
    _seed(["000111", "000222"], listings_only=["000333"])

    asked: list[str] = []
    monkeypatch.setattr(kr_fundamentals, "is_cached", lambda code, **kw: False)
    monkeypatch.setattr(kr_insider, "is_cached", lambda code, **kw: True)
    monkeypatch.setattr(kr_fundamentals, "get_report", lambda code: asked.append(code))

    ingest._precollect_kr_dart()
    assert "000333" not in asked, "사이트맵에 없는 종목을 모으면 광고와 어긋난다"
    assert set(asked) <= {"000111", "000222"}


def test_it_does_not_refetch_what_is_already_cached(dart_open, monkeypatch) -> None:
    """이미 있는 것을 다시 부르면 주기당 예산이 거기서 다 나간다."""
    _seed(["000111", "000222"])
    calls: list[str] = []
    monkeypatch.setattr(kr_fundamentals, "is_cached", lambda code, **kw: True)
    monkeypatch.setattr(kr_insider, "is_cached", lambda code, **kw: True)
    monkeypatch.setattr(kr_fundamentals, "get_report", lambda code: calls.append(code))
    monkeypatch.setattr(kr_insider, "get_reports", lambda code: calls.append(code))

    assert ingest._precollect_kr_dart() == 0
    assert calls == [], "캐시가 있는데 상류를 불렀다"


def test_it_stops_at_the_daily_limit(dart_open, monkeypatch) -> None:
    """다른 수집이 같은 한도를 나눠 쓴다. 한 번에 다 쓰면 그날 나머지가 굶는다."""
    _seed(["000111", "000222", "000333"])
    monkeypatch.setattr(kr_fundamentals, "is_cached", lambda code, **kw: False)
    monkeypatch.setattr(kr_insider, "is_cached", lambda code, **kw: False)

    tries: list[str] = []

    def limited(code):
        tries.append(code)
        raise RateLimited("daily quota")

    monkeypatch.setattr(kr_fundamentals, "get_report", limited)
    monkeypatch.setattr(kr_insider, "get_reports", limited)

    assert ingest._precollect_kr_dart() == 0
    assert len(tries) == 1, f"한도를 만나고도 계속 불렀다: {tries}"


def test_one_failure_does_not_stop_the_rest(dart_open, monkeypatch) -> None:
    """한 종목의 DART 실패가 나머지 종목을 막으면 커버리지가 거기서 멈춘다."""
    _seed(["000111", "000222"])
    monkeypatch.setattr(kr_fundamentals, "is_cached", lambda code, **kw: False)
    monkeypatch.setattr(kr_insider, "is_cached", lambda code, **kw: True)

    seen: list[str] = []

    def flaky(code):
        seen.append(code)
        if code == "000111":
            raise ValueError("DART가 이 종목에 400을 줬다")

    monkeypatch.setattr(kr_fundamentals, "get_report", flaky)
    ingest._precollect_kr_dart()
    assert len(seen) == 2, f"첫 실패에서 멈췄다: {seen}"


def test_a_closed_lane_collects_nothing(dart_open, monkeypatch) -> None:
    """게이트가 닫혀 있으면 아무것도 부르지 않는다 — 키 없이 호출하면 로그만 더럽다."""
    _seed(["000111"])
    monkeypatch.setattr(config, "DART_ENABLED", False)
    monkeypatch.setattr(kr_fundamentals, "is_cached", lambda code, **kw: False)

    # 예외로 확인하면 안 된다 — 사전수집의 `except Exception`이 그것을 삼켜서
    # 게이트가 없어도 테스트가 통과한다(실제로 그렇게 통과했다).
    called: list[str] = []
    monkeypatch.setattr(kr_fundamentals, "get_report", lambda code: called.append(code))
    monkeypatch.setattr(kr_insider, "get_reports", lambda code: called.append(code))

    assert ingest._precollect_kr_dart() == 0
    assert called == [], f"게이트가 닫혔는데 상류를 불렀다: {called}"


def test_the_batch_actually_runs_it(dart_open) -> None:
    """함수만 있고 부르는 곳이 없으면 아무 일도 일어나지 않는다."""
    import inspect

    source = inspect.getsource(ingest)
    assert 'result["dart_precollected"] = _precollect_kr_dart()' in source, (
        "배치가 이 단계를 부르지 않는다"
    )


def test_coverage_tolerance_is_not_the_serving_freshness(dart_open, monkeypatch) -> None:
    """숫자 하나가 두 질문에 답하면 예산이 안 맞는다.

    처음에 `DART_MAX_AGE`(12시간) 하나로 썼다가 실측에서 막혔다: 640건을 하루
    두 번 갱신하려면 1,280건/일이 필요한데 예산은 8×96 = 768건/일이라, 신규
    확보와 갱신이 서로 예산을 뺏으며 60% 언저리에서 정체한다.

    연간 재무제표는 분기에 한 번 바뀐다. 커버리지 목적에서 사흘 지난 값은
    **없는 것보다 낫다** — 그래서 허용치를 따로 둔다.
    """
    assert config.KR_DART_COVERAGE_MAX_AGE > config.DART_MAX_AGE, (
        "커버리지 허용치가 서빙 신선도보다 짧으면 예산이 갱신에만 쓰인다"
    )

    _seed(["000111"])
    asked: list[int] = []

    def spy(code, *, max_age):
        asked.append(max_age)
        return True

    monkeypatch.setattr(kr_fundamentals, "is_cached", spy)
    monkeypatch.setattr(kr_insider, "is_cached", spy)
    ingest._precollect_kr_dart()

    assert asked, "사전수집이 캐시 여부를 묻지 않았다"
    assert set(asked) == {config.KR_DART_COVERAGE_MAX_AGE}, (
        f"사전수집이 서빙 신선도로 물었다: {set(asked)}"
    )


def test_the_serving_path_still_uses_the_short_freshness() -> None:
    """사용자가 보는 값의 기준은 안 바뀌어야 한다 — 이 작업은 배치 이야기다."""
    import inspect

    for module in (kr_fundamentals, kr_insider):
        source = inspect.getsource(module)
        assert "config.DART_MAX_AGE" in source, (
            f"{module.__name__}의 서빙 경로가 짧은 신선도를 잃었다"
        )
