"""식약처 허가 그 후 — 허가 이벤트 주가 추적.

무엇을 고정하는가: 이름 매칭은 정규화 후 정확 일치·로스터 유일일 때만이다
(오매칭보다 결측 — 지수명·동명이인 함정의 재적용), 수집은 저장된 mfds blob만
읽고 상류를 부르지 않는다, 채점은 5% 엔진과 같은 규칙(기준가 동결·연쇄곱·
정지 감지·T+1 대기)을 공유 함수로 쓴다, 요청 경로는 저장소만 읽고 게이트는
fail-closed다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import bio, bio_events, config, ingest, store
from app.main import app

TODAY = dt.date(2026, 8, 27)


@pytest.fixture
def bio_events_lane(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "MFDS_ENABLED", True)
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-fsc-key")


def _roster(rows):
    store.save_kr_listings(
        [{"srtn_cd": code, "itms_nm": name, "mrkt_ctg": market,
          "isin_cd": "", "clpr": clpr, "flt_rt": 0.0, "mrkt_tot_amt": 1.0}
         for code, name, market, clpr in rows],
        "2026-08-26",
    )


def _permit(**overrides):
    row = {
        "item_seq": "202602492", "item_name": "브이테라잔정20밀리그램",
        "entp_name": "(주)종근당", "permit_date": "2026-08-20",
        "permit_kind": "허가", "etc_otc": "전문의약품",
        "newdrug_class": None, "rare": False,
        "url": "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=202602492",
    }
    row.update(overrides)
    return row


def _save_mfds_blob(permits):
    store.save_report(bio.MFDS_CACHE_KEY, {"permits": permits})


def _daily(date, close, flt_rt, volume=1000):
    return {"date": date, "close": close, "vs": None, "flt_rt": flt_rt, "volume": volume}


def _flat_rows(start, count, *, close=1000.0, volume=1000):
    return [
        _daily(start + dt.timedelta(days=i), close, 0.0 if i else None, volume)
        for i in range(count)
    ]


class FakeFsc:
    def __init__(self, stock_rows=None, index_rows=None):
        self.stock_rows = stock_rows or {}
        self.index_rows = index_rows or {}
        self.stock_calls: list[tuple] = []

    def fetch_stock_rows(self, code, *, start, end):
        self.stock_calls.append((code, start, end))
        return [r for r in self.stock_rows.get(code, []) if start <= r["date"] <= end]

    def fetch_index_rows(self, idx_nm, *, start, end):
        return [r for r in self.index_rows.get(idx_nm, []) if start <= r["date"] <= end]


# --- 이름 매칭 ---------------------------------------------------------------


def test_matching_is_exact_unique_after_normalisation(db):
    _roster([
        ("185750", "종근당", "KOSPI", 100000.0),
        ("000001", "쌍둥이", "KOSPI", 1000.0),
        ("000002", "쌍둥이", "KOSDAQ", 2000.0),  # 정규화명 충돌 — 매칭 금지
        ("069620", "대웅제약", "KOSPI", 150000.0),
    ])
    roster = bio_events.roster_map()

    assert bio_events._match("(주)종근당", roster) == ("185750", "Y")
    assert bio_events._match("주식회사 종근당", roster) == ("185750", "Y")
    # "OO제약(주)"가 로스터에 "OO"로만 있는 변형은 접미사 제거로 잡는다.
    _roster([("012345", "테스트", "KOSDAQ", 500.0)])
    roster = bio_events.roster_map()
    assert bio_events._match("테스트제약(주)", roster) == ("012345", "K")
    # 충돌 이름과 미상장은 결측이다 — 만들지 않는다.
    assert bio_events._match("쌍둥이", bio_events.roster_map()) is None
    assert bio_events._match("없는회사", bio_events.roster_map()) is None


def test_collect_reads_the_stored_blob_and_keeps_listed_matches_only(db, bio_events_lane):
    _roster([("185750", "종근당", "KOSPI", 100000.0)])
    _save_mfds_blob([
        _permit(),
        _permit(item_seq="202602493", entp_name="비상장바이오(주)"),
        _permit(item_seq="202602492"),  # 같은 품목 재등장 — 원장은 한 행
    ])

    stats = bio_events.collect(today=TODAY)

    assert stats == {"permits": 3, "matched": 2}  # upsert라 재등장은 덮어쓸 뿐
    events = store.load_bio_events(10)
    assert len(events) == 1
    event = events[0]
    assert event["event_id"] == "mfds:202602492"
    assert event["stock_code"] == "185750"
    assert event["market"] == "Y"
    assert bool(event["rx"]) is True
    assert event["base_status"] == "pending"


def test_recollect_never_clobbers_scoring_state(db, bio_events_lane):
    _roster([("185750", "종근당", "KOSPI", 100000.0)])
    _save_mfds_blob([_permit()])
    bio_events.collect(today=TODAY)
    store.set_bio_event_base(
        "mfds:202602492", status="ok",
        base_date=dt.date(2026, 8, 21), base_close=99000.0,
    )

    bio_events.collect(today=TODAY)

    event = store.load_bio_events(1)[0]
    assert event["base_status"] == "ok"
    assert event["base_close"] == 99000.0


# --- 채점 --------------------------------------------------------------------


def test_score_freezes_base_and_scores_ripe_horizons_in_one_fetch(db, bio_events_lane):
    _roster([("185750", "종근당", "KOSPI", 100000.0)])
    event_date = dt.date(2026, 5, 1)
    _save_mfds_blob([_permit(permit_date="2026-05-01")])
    bio_events.collect(today=TODAY)
    rows = _flat_rows(event_date + dt.timedelta(days=3), 30, close=100000.0)
    rows[5]["flt_rt"] = 2.0
    fsc = FakeFsc(stock_rows={"185750": rows},
                  index_rows={"코스피": _flat_rows(event_date, 130, close=2500.0)})

    stats = bio_events.score(fsc, today=TODAY)

    assert stats["bases"] == 1
    assert stats["scored"] == 1  # 30행이라 +21만 익었다
    assert len(fsc.stock_calls) == 1
    event = store.load_bio_events(1)[0]
    assert event["base_status"] == "ok"
    assert str(event["base_date"]) == "2026-05-04"
    checkpoint = event["checkpoints"][0]
    assert checkpoint["horizon"] == 21
    assert checkpoint["stock_return"] == pytest.approx(2.0, abs=0.01)


def test_score_waits_for_t_plus_one_and_flags_a_halted_base(db, bio_events_lane):
    _roster([("185750", "종근당", "KOSPI", 100000.0), ("028300", "에이치엘비", "KOSDAQ", 50000.0)])
    _save_mfds_blob([
        _permit(permit_date="2026-08-26"),  # 어제 허가 — 종가 미공개
        _permit(item_seq="202602599", entp_name="(주)에이치엘비", permit_date="2026-08-20"),
    ])
    bio_events.collect(today=TODAY)
    fsc = FakeFsc(stock_rows={
        "028300": [_daily(dt.date(2026, 8, 20), 50000.0, 0.0, volume=0)],
        "185750": [],
    })

    stats = bio_events.score(fsc, today=TODAY)

    events = {e["event_id"]: e for e in store.load_bio_events(10)}
    assert events["mfds:202602599"]["base_status"] == "ok"
    assert bool(events["mfds:202602599"]["base_halted"]) is True
    # 어제 허가는 T+1 13시 전이라 빈 응답 — 실패가 아니라 '대기'다.
    assert events["mfds:202602492"]["base_status"] == "pending"
    assert stats["waiting"] == 1
    assert stats["bases"] == 1


# --- 보드와 서빙 -------------------------------------------------------------


def _full_refresh(db):
    _roster([("185750", "종근당", "KOSPI", 103000.0)])
    _save_mfds_blob([_permit(permit_date="2026-05-01", rare=True)])
    event_date = dt.date(2026, 5, 1)
    fsc = FakeFsc(
        stock_rows={"185750": _flat_rows(event_date + dt.timedelta(days=3), 30, close=100000.0)},
        index_rows={"코스피": _flat_rows(event_date, 130, close=2500.0)},
    )
    return bio_events.refresh(fsc, today=TODAY)


def test_board_shape_matches_the_bio_payload_convention(db, bio_events_lane):
    stats = _full_refresh(db)

    assert stats["board_events"] == 1
    board = bio_events.get_board()
    assert board["schema"] == bio_events.SCHEMA
    assert "추천이 아닙니다" in board["disclaimer"]["ko"]
    assert "유일" in board["methodology"]["ko"]
    card = board["events"][0]
    assert card["stock_code"] == "185750"
    assert card["rare"] is True
    assert card["base"]["close"] == 100000.0
    # '현재'는 저장된 하루 스냅샷의 원시 비율 참고값이다.
    assert card["live"]["vs_base_percent"] == pytest.approx(3.0, abs=0.01)


def test_route_serves_the_stored_board_only(db, bio_events_lane, monkeypatch):
    _full_refresh(db)
    monkeypatch.setattr(bio_events, "_fsc",
                        lambda: pytest.fail("the request path must not call FSC"))

    response = TestClient(app).get("/api/bio/outcomes")

    assert response.status_code == 200
    assert response.json()["events"][0]["event_id"] == "mfds:202602492"


def test_route_fails_closed_and_reports_collecting(db, bio_events_lane, monkeypatch):
    client = TestClient(app)

    response = client.get("/api/bio/outcomes")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "bio_outcomes_collecting"

    monkeypatch.setattr(config, "FSC_ENABLED", False)
    response = client.get("/api/bio/outcomes")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "bio_outcomes_disabled"

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "MFDS_ENABLED", False)
    response = client.get("/api/bio/outcomes")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "bio_outcomes_disabled"


# --- ingest ------------------------------------------------------------------


def test_ingest_respects_freshness_and_schema(db, bio_events_lane, monkeypatch):
    calls = []
    monkeypatch.setattr(bio_events, "refresh", lambda: calls.append(1) or {"ok": 1})

    assert ingest.refresh_bio_events() == {"ok": 1}
    assert calls == [1]

    store.save_report(bio_events.CACHE_KEY, {"schema": bio_events.SCHEMA})
    assert ingest.refresh_bio_events() == {"skipped": "fresh"}
    assert calls == [1]

    # 모양이 다르면 신선해도 다시 걷는다 — 배치 blob 사고의 재발 방지 규칙.
    store.save_report(bio_events.CACHE_KEY, {"schema": bio_events.SCHEMA - 1})
    assert ingest.refresh_bio_events() == {"ok": 1}
    assert calls == [1, 1]


def test_ingest_skips_cleanly_while_the_lane_is_closed(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", False)
    assert ingest.refresh_bio_events() == {"skipped": "disabled"}
