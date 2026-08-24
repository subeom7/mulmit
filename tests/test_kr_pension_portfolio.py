"""국민연금 국내주식 포트폴리오 — 원자료를 고치지 않았는지 기계로 묶는다.

이 lane에서 틀리기 가장 쉬운 것은 **보기 좋게 만들려다 숫자를 고치는 것**이다.
원자료의 비중 컬럼은 1,200행을 다 더해도 100%가 아니라 99.37%다(공단이 소수
둘째 자리에서 반올림한 결과). 파이 차트를 그리다 보면 100%로 맞추고 싶어지는데,
그렇게 하는 순간 화면에 공단이 내지 않은 숫자가 선다.

그래서 여기 있는 검사 대부분은 "정규화하지 않았다"를 확인한다. 기능이 아니라
정직성을 지키는 검사이고, 나중에 누군가 "합이 100이 아니네" 하고 고치려 할 때
막아 서는 것이 목적이다.
"""

from __future__ import annotations

import csv
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import kr_pension_portfolio as portfolio
from app.main import app

client = TestClient(app)

# 파일을 열어 직접 읽은 값. 모듈을 거치지 않고 비교할 기준이 필요하다.
with portfolio.DATA_FILE.open(encoding="utf-8", newline="") as _handle:
    RAW_ROWS = list(csv.DictReader(_handle))


@pytest.fixture(scope="module")
def payload() -> dict:
    response = client.get("/api/kr/pension-portfolio")
    assert response.status_code == 200, response.text
    return response.json()


# --- 파일 자체 ---------------------------------------------------------------

def test_the_csv_ships_with_the_repo():
    """lane이 아니라 파일이 원천이다. 파일이 빠지면 배포가 조용히 반쪽이 된다.

    존재만 보면 부족하다 — 개발 머신에는 있는데 `.gitignore`에 걸려 이미지에는
    없는 경우가 정확히 "CI는 초록인데 라이브만 비어 있는" 사고다. 이미지는
    `COPY app ./app`으로 통째로 담으므로, **git이 이 파일을 추적하는가**가
    배포에 들어가는지와 같은 질문이 된다.
    """
    assert portfolio.DATA_FILE.exists(), portfolio.DATA_FILE

    repo = portfolio.DATA_FILE.parents[2]
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(portfolio.DATA_FILE)],
            cwd=repo, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git 없는 환경
        pytest.skip("git을 부를 수 없다")
    assert tracked.returncode == 0, (
        "CSV가 git에 없다 — 이미지에도 안 들어가고 라이브에서만 lane이 사라진다"
    )


def test_the_header_is_the_one_the_parser_expects():
    """컬럼명이 미묘하다 — `평가액(억 원)`은 억과 원 사이에 공백이 있고
    퍼센트 칸은 `(%)`가 아니라 `(퍼센트)`다. 내년 파일에서 이게 바뀌면
    파서가 조용히 0을 채우므로 여기서 걸리게 한다."""
    assert list(RAW_ROWS[0].keys()) == [
        "번호", "종목명", "평가액(억 원)", "자산군 내 비중(퍼센트)", "지분율(퍼센트)",
    ]


def test_the_file_has_every_row():
    assert len(RAW_ROWS) == 1200


# --- 원자료를 고치지 않았는가 -------------------------------------------------

def test_weights_are_relayed_not_normalised(payload):
    """합이 100이 아닌 것이 정상이다. 100이 되면 누군가 정규화한 것이다."""
    weight_sum = payload["totals"]["weight_sum"]
    assert weight_sum == pytest.approx(99.37, abs=0.01), weight_sum
    assert weight_sum != 100, "비중을 100%로 정규화했다 — 원자료는 99.37%다"


def test_each_slice_label_matches_the_file(payload):
    """조각에 찍히는 %는 파일의 값 그대로여야 한다."""
    by_name = {row["종목명"]: row for row in RAW_ROWS}
    for slice_ in payload["slices"]:
        if slice_["kind"] != "holding":
            continue
        raw = by_name[slice_["name"]]
        assert slice_["weight"] == float(raw["자산군 내 비중(퍼센트)"])
        assert slice_["value"] == float(raw["평가액(억 원)"])
        assert slice_["stake"] == float(raw["지분율(퍼센트)"])


def test_the_top_holding_is_untouched(payload):
    """가장 눈에 띄는 값이라 가장 먼저 고쳐지기 쉽다."""
    top = payload["slices"][0]
    assert top["name"] == "삼성전자"
    assert top["value"] == 230421.0
    assert top["weight"] == 16.7


# --- 그림의 기하 -------------------------------------------------------------

def test_angles_are_drawn_from_value_and_close_the_circle(payload):
    """각도는 평가액에서 나오므로 정확히 100%가 되어야 한다 — 잔차가 남으면
    도넛에 빈 틈이 생긴다."""
    total = sum(slice_["share"] for slice_ in payload["slices"])
    assert total == pytest.approx(100.0, abs=1e-6), total


def test_labels_and_angles_are_allowed_to_disagree(payload):
    """둘의 출처가 다르다는 것이 이 lane의 설계다. 완전히 같아졌다면 둘 중
    하나가 다른 하나로 대체된 것이고, 그러면 위의 두 성질 중 하나가 깨진다."""
    rest = payload["slices"][-1]
    assert rest["kind"] == "rest"
    assert rest["weight"] != pytest.approx(rest["share"], abs=1e-9)


def test_the_rest_slice_accounts_for_everything_else(payload):
    rest = payload["slices"][-1]
    named = [s for s in payload["slices"] if s["kind"] == "holding"]

    assert len(named) == portfolio.SLICE_COUNT
    assert rest["count"] == len(RAW_ROWS) - portfolio.SLICE_COUNT
    tail_value = sum(float(row["평가액(억 원)"]) for row in RAW_ROWS[portfolio.SLICE_COUNT:])
    assert rest["value"] == pytest.approx(tail_value, abs=0.01)


def test_named_slices_are_the_majority(payload):
    """20이라는 수를 고른 이유가 이것이다. 이 성질이 깨지면 `기타`가 최대
    조각이 되어 그림이 보유 종목이 아니라 나머지를 말하게 된다."""
    named = sum(s["weight"] for s in payload["slices"] if s["kind"] == "holding")
    assert named > 50, f"이름 붙은 조각이 과반이 아니다({named}%) — SLICE_COUNT를 올려라"


# --- 화면이 말해야 하는 사정 --------------------------------------------------

def test_the_as_of_date_travels_with_the_numbers(payload):
    """연 1회 갱신이라 낡음이 이 lane의 가장 큰 위험이다. 기준일이 payload에
    없으면 화면이 그것을 말할 방법이 없다."""
    assert payload["as_of"] == "2024-12-31"
    assert payload["next_release"] == "2026-09-30"
    assert "2024-12-31" in payload["basis_ko"]
    assert "2024-12-31" in payload["basis_en"]


def test_the_long_tail_is_counted(payload):
    """749종목은 비중이 0.00%로 반올림된다. `1,200종목`이라는 말이 무엇을
    뜻하는지 화면이 정직하게 말하려면 이 수가 필요하다."""
    totals = payload["totals"]
    assert totals["rounded_out_count"] == 749
    assert totals["rounded_out_value"] == pytest.approx(11857.0, abs=1)
    # 종목 수로는 62%지만 금액으로는 1%가 안 된다 — 그 대비가 요점이다.
    assert totals["rounded_out_value"] / totals["value"] < 0.01


def test_attribution_names_the_publisher_and_the_licence(payload):
    source = payload["source"]
    assert source["publisher"] == "국민연금공단"
    assert "data.go.kr" in source["url"]
    assert source["licence"] == "이용허락범위 제한 없음"
    assert "2024-12-31" in source["notice"]


def test_the_response_is_cached_for_a_day(payload):
    """이미지 안에서 바뀌지 않는 파일이라 짧게 잡을 이유가 없다."""
    response = client.get("/api/kr/pension-portfolio")
    assert response.headers["cache-control"] == "public, max-age=86400"


# --- 배포되면 실제로 보이는가 -------------------------------------------------
#
# CI가 초록인데 라이브가 틀린 사고를 이 저장소에서 여러 번 겪었다. 서버가 옳은
# JSON을 줘도 화면이 그것을 부르지 않으면 아무도 못 본다.

def test_the_page_carries_the_section_the_renderer_looks_for():
    kr_html = (portfolio.DATA_FILE.parents[1] / "static" / "kr.html").read_text(encoding="utf-8")
    for node_id in ('id="kr-pension-portfolio"', 'id="krpf-body"', 'id="krpf-footer"'):
        assert node_id in kr_html, f"{node_id}가 kr.html에 없다"


def test_the_script_fetches_the_endpoint_on_the_kr_page():
    monitor = (portfolio.DATA_FILE.parents[1] / "static" / "monitor.js").read_text(encoding="utf-8")
    assert 'krPensionPortfolio: ["kr"]' in monitor, "PAGE_FETCHES에 없다 — /kr에서 아예 부르지 않는다"
    assert '"/api/kr/pension-portfolio", "krPensionPortfolio"' in monitor
    assert "renderKrPensionPortfolio();" in monitor, "렌더러를 호출하는 곳이 없다"


@pytest.mark.parametrize("key", [
    "krpf.title", "krpf.copy", "krpf.asOf", "krpf.rest", "krpf.restCount",
    "krpf.colWeight", "krpf.weightNote", "krpf.tailNote", "krpf.colValue",
])
def test_both_languages_have_every_string(key: str):
    """한쪽 언어에만 넣어 두면 다른 언어에서 키 이름이 그대로 화면에 뜬다."""
    monitor = (portfolio.DATA_FILE.parents[1] / "static" / "monitor.js").read_text(encoding="utf-8")
    assert monitor.count(f'"{key}":') == 2, f"{key}가 ko/en 양쪽에 있지 않다"
