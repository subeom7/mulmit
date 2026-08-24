"""국민연금 국내주식 포트폴리오 — 연말 스냅샷.

이 저장소에서 **처음으로 파일이 원천인 lane**이다. 다른 lane은 모두 API를
때리지만 이것은 `app/data/`에 들어 있는 CSV를 읽는다. 그렇게 한 이유는 원천이
그런 모양이기 때문이다 — 공공데이터포털 3070507은 오픈API가 없는 파일데이터고,
**연 1회** 갱신된다. 1년에 한 번 바뀌는 것에 키·쿼터·수집 배치를 붙이면 얻는
것 없이 깨질 곳만 늘어난다.

출처: [국민연금공단_국내주식 투자정보](https://www.data.go.kr/data/3070507/fileData.do)
이용허락범위 **제한 없음**(상업적 이용·변형 허용). 파일 원문은 CP949였고
저장소에는 UTF-8로 인코딩만 바꿔 넣었다 — 값은 한 칸도 고치지 않았다.

기존 `kr_pension`(DART 5% 공시)과 헷갈리기 쉬운데 서로 다른 것을 잰다:

    kr_pension            5% 룰 공시 · **회사 대비** 지분율 · 현재형 · 5% 넘긴 종목만
    kr_pension_portfolio  연말 스냅샷 · **포트폴리오 대비** 비중 · 전 종목 1,200개

원형 차트가 필요로 하는 것은 뒤쪽(자산군 내 비중)인데 5% 공시에는 그 값이 없다.

숫자를 다루며 조심한 곳
-----------------------
**비중 컬럼의 합은 100%가 아니라 99.37%다.** 소수 둘째 자리 반올림이 1,200번
쌓인 결과다. 100%로 정규화하면 보기에는 깔끔하지만 그것은 공단이 내지 않은
숫자를 화면에 세우는 일이라 하지 않는다. 대신 이렇게 나눴다:

* **조각의 각도**는 평가액(억 원)으로 그린다 — 정수라 반올림 잔차가 없고
  합이 총액과 정확히 맞는다.
* **화면에 찍히는 %**는 원자료의 비중 값을 그대로 옮긴다.
* `기타`의 %는 21위 이하 행들의 비중을 **더한 값**이다(발명이 아니라 합계).

그래서 라벨의 합은 99.37%이고, 그 사실 자체를 푸터에 적는다.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent / "data" / "nps_domestic_equity_20241231.csv"

#: 파일이 담고 있는 시점. 파일명과 함께 손으로 바꾼다 — 1년에 한 번 있는 일이다.
AS_OF = "2024-12-31"

#: 다음 파일 예정일. 화면에 "얼마나 낡았는지"를 말하기 위해 쓴다.
NEXT_RELEASE = "2026-09-30"

#: 이름을 붙여 그릴 조각 수. 20인 이유는 **이름 붙은 조각이 과반이 되는 가장
#: 작은 수**이기 때문이다(상위 20 = 53.48%, 상위 15 = 48.75%). 15로 줄이면
#: `기타`가 최대 조각이 되어 그림이 "나머지"를 말하게 된다.
SLICE_COUNT = 20

#: 표로 보여줄 행 수. 차트보다 깊게 보되 1,200행을 다 내리지는 않는다.
TABLE_ROWS = 50

PUBLISHER = "국민연금공단"
PUBLISHER_EN = "National Pension Service"
DATASET_URL = "https://www.data.go.kr/data/3070507/fileData.do"
PORTAL = "공공데이터포털"

ATTRIBUTION = (
    "공공데이터포털 국민연금공단_국내주식 투자정보(이용허락범위 제한 없음)를 "
    f"가공하여 표시합니다. 기준일 {AS_OF}."
)
ATTRIBUTION_EN = (
    "Derived from the Korea Public Data Portal dataset "
    "'National Pension Service — domestic equity holdings' (open licence, no restrictions). "
    f"As of {AS_OF}."
)


class Holding(dict):
    """행 하나. dict를 그대로 쓰되 이름을 붙여 읽는 곳에서 뜻이 보이게 한다."""


def _to_float(raw: str) -> float:
    """빈 칸과 하이픈을 0으로 본다 — 원자료에 결측은 없었지만 파일이 바뀔 수 있다."""
    text = (raw or "").strip().replace(",", "")
    if not text or text == "-":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[Holding, ...]:
    """CSV를 한 번만 읽어 캐시한다. 파일은 배포 이미지 안에서 바뀌지 않는다."""
    with DATA_FILE.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        parsed: list[Holding] = []
        for raw in reader:
            name = (raw.get("종목명") or "").strip()
            if not name:
                continue
            parsed.append(
                Holding(
                    rank=int(_to_float(raw.get("번호", "0"))) or len(parsed) + 1,
                    name=name,
                    value=_to_float(raw.get("평가액(억 원)", "")),
                    weight=_to_float(raw.get("자산군 내 비중(퍼센트)", "")),
                    stake=_to_float(raw.get("지분율(퍼센트)", "")),
                )
            )
    return tuple(parsed)


def _slices(rows: tuple[Holding, ...], total_value: float) -> list[dict[str, Any]]:
    """상위 N개 + `기타`. 각도는 평가액, 라벨은 원자료의 비중."""
    named = rows[:SLICE_COUNT]
    rest = rows[SLICE_COUNT:]

    out: list[dict[str, Any]] = []
    for row in named:
        out.append(
            {
                "name": row["name"],
                "value": row["value"],
                "weight": row["weight"],
                "stake": row["stake"],
                # 그림을 그리는 비율. 라벨(weight)과 미세하게 다를 수 있고,
                # 그것이 원자료의 반올림이라는 사실은 푸터가 말한다.
                "share": (row["value"] / total_value * 100) if total_value else 0.0,
                "kind": "holding",
            }
        )

    if rest:
        rest_value = sum(row["value"] for row in rest)
        out.append(
            {
                "name": None,  # 화면이 각 언어로 "기타"를 붙인다.
                "value": rest_value,
                "weight": round(sum(row["weight"] for row in rest), 2),
                "stake": None,
                "share": (rest_value / total_value * 100) if total_value else 0.0,
                "kind": "rest",
                "count": len(rest),
            }
        )
    return out


def build_payload() -> dict[str, Any]:
    rows = _rows()
    total_value = sum(row["value"] for row in rows)
    weight_sum = round(sum(row["weight"] for row in rows), 2)

    # 평가액이 1억 미만이라 0으로 떨어진 행. "1,200종목"이라는 말이 무엇을
    # 뜻하는지 정직하게 말하려면 이 수가 필요하다.
    zero_value = sum(1 for row in rows if row["value"] <= 0)
    # 비중이 0.00%로 반올림된 행 — 평가액은 있는데 비중 칸이 0인 긴 꼬리다.
    rounded_out = [row for row in rows if row["weight"] <= 0]

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "as_of": AS_OF,
        "next_release": NEXT_RELEASE,
        "slices": _slices(rows, total_value),
        "holdings": [dict(row) for row in rows[:TABLE_ROWS]],
        "totals": {
            "count": len(rows),
            "value": total_value,
            "value_unit": "억원",
            # 100이 아니다. 그 사실이 화면까지 가야 해서 반올림해 실어 보낸다.
            "weight_sum": weight_sum,
            "zero_value_count": zero_value,
            "rounded_out_count": len(rounded_out),
            "rounded_out_value": sum(row["value"] for row in rounded_out),
            "slice_count": SLICE_COUNT,
            "table_rows": min(TABLE_ROWS, len(rows)),
        },
        # 반올림 사정은 화면이 `krpf.weightNote`로 따로 말한다. 여기서 또 하면
        # 푸터에 같은 문장이 두 번 선다(2026-08-24 로컬에서 눈으로 확인).
        "basis_ko": (
            f"국민연금공단이 {AS_OF} 기준으로 공시한 국내주식 종목별 평가액과 "
            "자산군 내 비중입니다. 연 1회 갱신되며 현재 보유와 다를 수 있습니다."
        ),
        "basis_en": (
            f"Domestic equity holdings published by the National Pension Service as of {AS_OF}: "
            "market value and share of the domestic-equity book. Updated once a year, so it "
            "may differ from current holdings."
        ),
        "source": {
            "provider": "nps_portfolio",
            "provider_name": PORTAL,
            "publisher": PUBLISHER,
            "publisher_en": PUBLISHER_EN,
            "url": DATASET_URL,
            "notice": ATTRIBUTION,
            "notice_en": ATTRIBUTION_EN,
            "licence": "이용허락범위 제한 없음",
        },
        "rights": {"status": "approved", "notice": ATTRIBUTION},
    }


def get_portfolio() -> dict[str, Any]:
    """라우트가 부르는 입구. 파일이 없으면 조용히 넘어가지 않고 터뜨린다."""
    if not DATA_FILE.exists():  # pragma: no cover - 이미지가 잘못 만들어진 경우
        raise FileNotFoundError(f"국민연금 포트폴리오 파일이 없다: {DATA_FILE}")
    return build_payload()
