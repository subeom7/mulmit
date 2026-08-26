"""대량보유(5%) 스코어보드 — 채점 엔진.

무엇을 고정하는가(전부 착수 전 프로브 실측에서 온 규칙이다, PLAN_SCORING §1):
이벤트는 원장에 쌓이고 채점 상태는 재수집이 덮지 못한다, 기준가는 공시일 이후
첫 거래일 종가로 동결된다(T+1 공개 전에는 대기 — 만들지 않는다), 수익률은
(1+fltRt) 연쇄곱이라 액면분할이 껴도 깨지지 않는다, 전 구간 거래정지는 0%가
아니라 채점 불능이다(도부 227420 실측), 보드 blob은 SCHEMA가 다르면 신선해도
다시 걷는다, 요청 경로는 저장소만 읽고 게이트는 fail-closed다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, kr_scoring, store
from app.main import app
from app.providers.base import DataUnavailable, RateLimited

TODAY = dt.date(2026, 8, 26)


@pytest.fixture
def scoring_lane(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "test-dart-key")
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-fsc-key")


def _index_row(**overrides):
    row = {
        "rcept_no": "20260820000111", "rcept_dt": "20260820",
        "corp_code": "00441243", "corp_name": "형지엘리트", "stock_code": "093240",
        "corp_cls": "Y", "report_nm": "주식등의대량보유상황보고서(일반)",
        "flr_nm": "대명화학",
    }
    row.update(overrides)
    return row


def _holding_row(**overrides):
    row = {
        "rcept_no": "20260820000111", "report_date": "2026-08-20",
        "report_type": "일반", "reporter": "대명화학",
        "shares": 1000000, "shares_change": 1000000,
        "ratio": 7.5, "ratio_change": 7.5,
        "reason": "매매로 인한 신규보고의무 발생",
        "report_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000111",
    }
    row.update(overrides)
    return row


def _daily(date, close, flt_rt, volume=1000):
    return {"date": date, "close": close, "vs": None, "flt_rt": flt_rt, "volume": volume}


def _flat_rows(start, count, *, close=1000.0, volume=1000):
    """주말 없는 가상 달력 — 채점 규칙은 달력이 아니라 행 수로 판정한다."""
    return [
        _daily(start + dt.timedelta(days=i), close, 0.0 if i else None, volume)
        for i in range(count)
    ]


class FakeDart:
    def __init__(self, index_rows=None, holdings_by_corp=None, truncated=False):
        self.index_rows = index_rows or []
        self.holdings = holdings_by_corp or {}
        self.truncated = truncated
        self.index_calls: list[tuple] = []
        self.detail_calls: list[str] = []

    def fetch_filing_index(self, *, detail_type, bgn_de, end_de, max_pages=60):
        self.index_calls.append((detail_type, bgn_de, end_de))
        return list(self.index_rows), self.truncated

    def fetch_major_holdings(self, corp_code):
        self.detail_calls.append(corp_code)
        result = self.holdings.get(corp_code)
        if isinstance(result, Exception):
            raise result
        return result or []


class FakeFsc:
    def __init__(self, stock_rows=None, index_rows=None):
        self.stock_rows = stock_rows or {}
        self.index_rows = index_rows or {}
        self.stock_calls: list[tuple] = []

    def fetch_stock_rows(self, code, *, start, end):
        self.stock_calls.append((code, start, end))
        rows = self.stock_rows.get(code)
        if isinstance(rows, Exception):
            raise rows
        return [r for r in rows or [] if start <= r["date"] <= end]

    def fetch_index_rows(self, idx_nm, *, start, end):
        return [r for r in self.index_rows.get(idx_nm, []) if start <= r["date"] <= end]


# --- 수집 --------------------------------------------------------------------


def test_collect_saves_listed_filings_once(db, scoring_lane):
    dart = FakeDart(index_rows=[
        _index_row(),
        _index_row(),  # 같은 rcept_no — 페이지 겹침
        _index_row(rcept_no="20260821000222", rcept_dt="20260821",
                   corp_code="00105952", corp_name="LS", stock_code="006260"),
        _index_row(rcept_no="20260822000333", stock_code=""),  # 비상장 — 채점 대상 아님
    ])

    stats = kr_scoring.collect(dart, today=TODAY)

    assert stats["saved"] == 2
    # 첫 수집은 설정된 과거 일수만큼 걷는다.
    begin = (TODAY - dt.timedelta(days=config.KR_SCORING_COLLECT_DAYS)).strftime("%Y%m%d")
    assert dart.index_calls == [("D001", begin, "20260826")]

    # 두 번째 수집은 마지막 저장일에서 사흘 겹쳐 이어 걷고, 원장을 불리지 않는다.
    stats2 = kr_scoring.collect(dart, today=TODAY)
    assert stats2["saved"] == 0
    assert dart.index_calls[-1] == ("D001", "20260818", "20260826")


def test_details_join_by_rcept_and_detect_new_entry(db, scoring_lane):
    dart = FakeDart(
        index_rows=[
            _index_row(),
            _index_row(rcept_no="20260821000222", rcept_dt="20260821",
                       corp_code="00105952", corp_name="LS", stock_code="006260"),
        ],
        holdings_by_corp={
            "00441243": [_holding_row()],
            "00105952": DataUnavailable("down"),
        },
    )
    kr_scoring.collect(dart, today=TODAY)

    stats = kr_scoring.fill_details(dart)

    assert stats["updated"] == 1
    assert stats["failed"] == 1
    events = {e["rcept_no"]: e for e in store.load_score_events(10)}
    joined = events["20260820000111"]
    assert joined["detail_status"] == "ok"
    assert joined["ratio"] == 7.5
    # 신규 판별은 report_tp가 아니라 자유 텍스트에만 있기도 하다(실측) — 둘 다 본다.
    assert joined["is_new"] is True
    failed = events["20260821000222"]
    assert failed["detail_status"] == "unavailable"
    assert failed["ratio"] is None


# --- 기준가 ------------------------------------------------------------------


def test_base_freezes_first_trading_close_after_filing(db, scoring_lane):
    dart = FakeDart(index_rows=[_index_row(rcept_dt="20260822")])  # 토요일
    kr_scoring.collect(dart, today=TODAY)
    fsc = FakeFsc(stock_rows={
        "093240": [_daily(dt.date(2026, 8, 24), 13950.0, None)],  # 다음 거래일 월요일
    })

    stats = kr_scoring.fill_bases(fsc, today=TODAY)

    assert stats["ok"] == 1
    event = store.load_score_events(1)[0]
    assert event["base_status"] == "ok"
    assert event["base_close"] == 13950.0
    assert bool(event["base_halted"]) is False


def test_base_waits_for_t_plus_one_and_never_invents(db, scoring_lane):
    """공식 종가는 T+1 13시 공개다 — 갓 나온 공시의 빈 응답은 '대기'지 실패가 아니다."""
    dart = FakeDart(index_rows=[_index_row(rcept_dt="20260826")])
    kr_scoring.collect(dart, today=TODAY)
    fsc = FakeFsc(stock_rows={"093240": []})

    stats = kr_scoring.fill_bases(fsc, today=TODAY)

    assert stats == {"pending": 1, "ok": 0, "no_data": 0, "waiting": 1}
    assert store.load_score_events(1)[0]["base_status"] == "pending"


def test_base_folds_to_no_data_when_the_window_stays_empty(db, scoring_lane):
    dart = FakeDart(index_rows=[_index_row(rcept_dt="20260701")])
    kr_scoring.collect(dart, today=TODAY)
    fsc = FakeFsc(stock_rows={"093240": []})

    kr_scoring.fill_bases(fsc, today=TODAY)

    assert store.load_score_events(1)[0]["base_status"] == "no_data"


def test_base_on_a_halted_day_is_flagged(db, scoring_lane):
    """도부(227420) 실측: 공시일에 이미 거래정지면 그 사실이 카드에 남아야 한다."""
    dart = FakeDart(index_rows=[_index_row(rcept_dt="20260820")])
    kr_scoring.collect(dart, today=TODAY)
    fsc = FakeFsc(stock_rows={
        "093240": [_daily(dt.date(2026, 8, 20), 1808.0, 0.0, volume=0)],
    })

    kr_scoring.fill_bases(fsc, today=TODAY)

    event = store.load_score_events(1)[0]
    assert event["base_status"] == "ok"
    assert bool(event["base_halted"]) is True


# --- 체크포인트 --------------------------------------------------------------


def _seed_based_event(*, rcept_dt="20260501", base_date=dt.date(2026, 5, 4),
                      base_close=1000.0, market="Y"):
    dart = FakeDart(index_rows=[_index_row(rcept_dt=rcept_dt, corp_cls=market)])
    kr_scoring.collect(dart, today=TODAY)
    store.set_score_base(
        "20260820000111", status="ok", base_date=base_date, base_close=base_close
    )


def test_checkpoint_chains_flt_rt_so_a_split_cannot_break_it(db, scoring_lane):
    """카카오 5:1 실측의 재현: 분할일 fltRt는 조정 기준가 대비라 연쇄곱이 안전하다.

    원시 종가비로 계산하면 −79%가 나와야 할 자리에서, 연쇄곱은 진짜 수익률을
    돌려준다.
    """
    base_date = dt.date(2026, 5, 4)
    rows = [_daily(base_date, 5000.0, None)]
    for i in range(1, 10):
        rows.append(_daily(base_date + dt.timedelta(days=i), 5000.0, 0.0))
    # 분할일: 종가는 1/5로 접히지만 등락률은 조정 기준가 대비 +2.0%다.
    rows.append(_daily(base_date + dt.timedelta(days=10), 1020.0, 2.0))
    for i in range(11, 22):
        rows.append(_daily(base_date + dt.timedelta(days=i), 1020.0, 0.0))
    kospi = _flat_rows(base_date, 22, close=2500.0)
    for row in kospi[1:]:
        row["flt_rt"] = 0.5

    _seed_based_event(base_date=base_date, base_close=5000.0)
    fsc = FakeFsc(stock_rows={"093240": rows}, index_rows={"코스피": kospi})

    stats = kr_scoring.score_checkpoints(fsc, today=TODAY)

    assert stats["scored"] == 1
    checkpoint = store.load_score_events(1)[0]["checkpoints"][0]
    assert checkpoint["horizon"] == 21
    assert checkpoint["status"] == "scored"
    assert checkpoint["stock_return"] == pytest.approx(2.0, abs=0.01)
    assert checkpoint["bench_return"] == pytest.approx((1.005 ** 21 - 1) * 100, abs=0.01)
    assert checkpoint["excess"] == pytest.approx(
        checkpoint["stock_return"] - checkpoint["bench_return"], abs=0.001
    )


def test_checkpoint_of_a_fully_halted_window_is_not_a_zero(db, scoring_lane):
    """도부 실측: 53거래일 전부 거래량 0 — 감지 없이는 '0% 수익'으로 위장된다."""
    base_date = dt.date(2026, 5, 4)
    rows = _flat_rows(base_date, 22, close=1808.0, volume=0)
    _seed_based_event(base_date=base_date, base_close=1808.0)
    fsc = FakeFsc(stock_rows={"093240": rows}, index_rows={"코스피": _flat_rows(base_date, 22)})

    stats = kr_scoring.score_checkpoints(fsc, today=TODAY)

    assert stats["halted"] == 1
    checkpoint = store.load_score_events(1)[0]["checkpoints"][0]
    assert checkpoint["status"] == "halted"
    assert checkpoint["stock_return"] is None
    assert checkpoint["excess"] is None


def test_checkpoint_waits_until_enough_trading_days(db, scoring_lane):
    base_date = dt.date(2026, 7, 1)
    _seed_based_event(rcept_dt="20260701", base_date=base_date)
    fsc = FakeFsc(stock_rows={"093240": _flat_rows(base_date, 10)},
                  index_rows={"코스피": _flat_rows(base_date, 10)})

    kr_scoring.score_checkpoints(fsc, today=TODAY)

    assert store.load_score_events(1)[0]["checkpoints"] == []


def test_checkpoints_are_frozen_once_scored(db, scoring_lane):
    """채점은 동결이다 — 다음 주기가 같은 horizon을 다시 계산하지 않는다."""
    base_date = dt.date(2026, 5, 4)
    rows = _flat_rows(base_date, 22)
    _seed_based_event(base_date=base_date)
    fsc = FakeFsc(stock_rows={"093240": rows}, index_rows={"코스피": _flat_rows(base_date, 22)})

    assert kr_scoring.score_checkpoints(fsc, today=TODAY)["scored"] == 1
    first = store.load_score_events(1)[0]["checkpoints"]

    # 두 번째 주기는 아직 안 찬 다음 horizon(63)을 살펴볼 수는 있어도,
    # 이미 동결된 +21을 다시 만들거나 덮지 않는다.
    assert kr_scoring.score_checkpoints(fsc, today=TODAY)["scored"] == 0
    assert store.load_score_events(1)[0]["checkpoints"] == first


# --- 보드와 서빙 -------------------------------------------------------------


def _run_full_refresh(db):
    dart = FakeDart(
        index_rows=[_index_row(rcept_dt="20260501")],
        holdings_by_corp={"00441243": [_holding_row()]},
    )
    base_date = dt.date(2026, 5, 4)
    fsc = FakeFsc(
        stock_rows={"093240": _flat_rows(base_date, 30, close=13950.0)},
        index_rows={"코스피": _flat_rows(base_date, 30, close=2500.0)},
    )
    return kr_scoring.refresh(dart, fsc, today=TODAY)


def test_board_blob_carries_schema_disclaimer_and_live_reference(db, scoring_lane):
    store.save_kr_listings(
        [{"srtn_cd": "093240", "itms_nm": "형지엘리트", "mrkt_ctg": "KOSPI",
          "isin_cd": "KR7093240007", "clpr": 15345.0, "flt_rt": 1.0,
          "mrkt_tot_amt": 1.0}],
        "2026-08-25",
    )

    stats = _run_full_refresh(db)

    assert stats["board_cards"] == 1
    board = kr_scoring.get_board()
    assert board["schema"] == kr_scoring.SCHEMA
    assert "추천이 아닙니다" in board["basis_ko"]
    assert "거래정지" in board["basis_ko"]
    card = board["cards"][0]
    assert card["company"] == "형지엘리트"
    assert card["is_new"] is True
    assert card["base"]["close"] == 13950.0
    # '현재'는 저장된 하루 스냅샷에서 온 원시 비율 참고값이다 — 상류 호출이 아니라.
    assert card["live"]["vs_base_percent"] == pytest.approx(10.0, abs=0.01)
    assert card["live"]["basis"] == "raw_close_ratio"
    assert card["checkpoints"][0]["horizon"] == 21


def test_api_serves_the_stored_board_only(db, scoring_lane, monkeypatch):
    _run_full_refresh(db)
    monkeypatch.setattr(kr_scoring, "_dart",
                        lambda: pytest.fail("the request path must not call DART"))
    monkeypatch.setattr(kr_scoring, "_fsc",
                        lambda: pytest.fail("the request path must not call FSC"))

    response = TestClient(app).get("/api/kr/score")

    assert response.status_code == 200
    body = response.json()
    assert body["cards"][0]["stock_code"] == "093240"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_api_is_503_before_the_first_batch(db, scoring_lane):
    response = TestClient(app).get("/api/kr/score")
    assert response.status_code == 503
    assert "not built" in response.json()["detail"]


def test_the_lane_fails_closed_when_either_gate_is_off(db, scoring_lane, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "FSC_ENABLED", False)
    response = client.get("/api/kr/score")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_scoring_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "")
    response = client.get("/api/kr/score")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_scoring_not_configured"


def test_ssr_page_renders_from_the_store_and_survives_empty(db, scoring_lane):
    client = TestClient(app)

    before = client.get("/score")
    assert before.status_code == 200
    assert "첫 채점 배치" in before.text

    _run_full_refresh(db)
    after = client.get("/score")
    assert after.status_code == 200
    assert "형지엘리트" in after.text
    assert "추천이 아닙니다" in after.text
    assert "/stock/093240" in after.text
    assert "{{" not in after.text  # 치환 안 된 플레이스홀더가 본문으로 새면 안 된다


# --- ingest ------------------------------------------------------------------


def test_ingest_respects_gates_freshness_and_schema(db, scoring_lane, monkeypatch):
    calls = []
    monkeypatch.setattr(kr_scoring, "refresh", lambda: calls.append(1) or {"ok": 1})

    monkeypatch.setattr(config, "FSC_ENABLED", False)
    assert ingest.refresh_kr_scoring() == {"skipped": "disabled"}
    monkeypatch.setattr(config, "FSC_ENABLED", True)

    assert ingest.refresh_kr_scoring() == {"ok": 1}
    assert calls == [1]

    # 신선하고 모양도 같으면 걷지 않는다.
    store.save_report(kr_scoring.CACHE_KEY, {"schema": kr_scoring.SCHEMA})
    assert ingest.refresh_kr_scoring() == {"skipped": "fresh"}
    assert calls == [1]

    # 신선해도 **모양이 다르면** 다시 걷는다 — 배포 직후 옛 blob이 화면을
    # 옛 모양으로 붙들던 사고의 재발 방지다(ROADMAP 2026-08-25).
    store.save_report(kr_scoring.CACHE_KEY, {"schema": kr_scoring.SCHEMA - 1})
    assert ingest.refresh_kr_scoring() == {"ok": 1}
    assert calls == [1, 1]


def test_ingest_swallows_a_rate_limit_into_a_skip(db, scoring_lane, monkeypatch):
    def throttled():
        raise RateLimited("quota")

    monkeypatch.setattr(kr_scoring, "refresh", throttled)

    assert ingest.refresh_kr_scoring() == {"skipped": "rate_limited"}
