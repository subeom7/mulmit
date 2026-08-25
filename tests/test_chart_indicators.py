"""보조지표가 캔들과 함께 다니는가.

운영자 지적(2026-08-25): "보조지표를 이것저것 여러 번 클릭하다 보면 차트에서
아무것도 안 나오면서 없어진다." 버튼은 켜진 채였다.

원인은 갱신 요청의 절약 옵션이었다. 클라이언트는 캔들을 이미 갖고 있으면
`?candles=false`로 물어 대역폭을 아끼는데, 서버는 그때 **지표도 함께 뺀다**:

    candles 포함     indicators: ma · bollinger · rsi · macd
    candles=false    indicators: None

캔들은 클라이언트가 따로 보관하면서 지표는 `lastPayload`를 통째로 갈아 끼우는
바람에 잃었다. 그 뒤로는 토글을 아무리 눌러도 그릴 것이 없다 — **에러도 로그도
없이** 버튼만 켜져 있다. 구간을 바꾸면 캔들을 다시 받으므로 잠깐 살아난다.

지표는 캔들에서 나온 값이다. 캔들을 남겨 두기로 했으면 지표도 같이 남겨야
하고, 캔들을 버릴 때 같이 버려야 한다 — 다른 구간의 지표를 이 캔들 위에 그리면
선이 어긋난 채로 멀쩡해 보인다.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "app" / "static" / "crypto-coin.html"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_chart_reads_a_kept_copy_not_the_latest_payload() -> None:
    source = _source()
    assert "const ind = indicators;" in source, (
        "lastPayload에서 읽으면 candles=false 응답 하나가 지표를 지운다"
    )
    assert "lastPayload?.chart?.indicators" not in source


def test_indicators_are_kept_beside_the_candles() -> None:
    source = _source()
    assert re.search(r"let candles = \[\], indicators = null", source), (
        "지표는 캔들과 같은 자리에서 관리해야 한다"
    )
    # 캔들을 새로 받는 자리에서 지표도 같이 받는다.
    block = source[source.index("if (needCandles &&") : source.index("} else if (candles.length")]
    assert "indicators = data.chart.indicators" in block


def test_changing_the_interval_drops_them_together() -> None:
    """다른 구간의 지표를 이 캔들 위에 그리면 선이 어긋난 채로 멀쩡해 보인다."""
    source = _source()
    line = next(row for row in source.splitlines() if "candles = []" in row and "load(true)" in row)
    assert "indicators = null" in line, f"구간을 바꿀 때 지표를 안 버린다: {line.strip()}"
