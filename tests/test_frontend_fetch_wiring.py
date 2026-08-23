"""The dashboard's fetch list is wired by position — check it stays lined up.

`loadCore()` builds one `Promise.all([...])` of `request(url, key)` calls and
destructures the results into names, then assigns each name to `state`. Nothing
connects the key inside `request(...)` to the name in the destructuring except
their order, so inserting a lane in the middle silently hands every later lane
the wrong payload. A separate `PAGE_FETCHES` map decides which pages fetch
which key; a key missing from it makes `onPage(...undefined)` throw and takes
the whole load down.

Both mistakes were made adding the liquidation lane, and neither shows up as a
failing request — the page just renders the wrong thing or nothing. So they are
checked here rather than left to review.
"""

from __future__ import annotations

import re
from pathlib import Path

MONITOR = Path(__file__).resolve().parents[1] / "app" / "static" / "monitor.js"


def _source() -> str:
    return MONITOR.read_text(encoding="utf-8")


def _load_core_block(source: str) -> str:
    start = source.index("async function loadCore()")
    end = source.index("function renderAll()", start)
    return source[start:end]


def _destructured_names(block: str) -> list[str]:
    match = re.search(r"const \[([^\]]+)\] = await Promise\.all\(\[", block)
    assert match, "loadCore no longer destructures a Promise.all — update this test"
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def _requested_keys(block: str) -> list[str]:
    body = block[block.index("await Promise.all([") :]
    return re.findall(r"""request\(\s*[^,]+,\s*["']([^"']+)["']\s*\)""", body)


def _page_fetch_keys(source: str) -> set[str]:
    start = source.index("const PAGE_FETCHES = {")
    end = source.index("};", start)
    return set(re.findall(r"^\s*(\w+)\s*:", source[start:end], re.M))


def test_every_result_lands_in_the_slot_its_request_occupies():
    block = _load_core_block(_source())
    names, keys = _destructured_names(block), _requested_keys(block)
    assert len(names) == len(keys), (
        f"{len(keys)} requests but {len(names)} destructured names — "
        "a lane was added to one list and not the other"
    )
    mismatched = [(i, name, key) for i, (name, key) in enumerate(zip(names, keys, strict=True)) if name != key]
    assert not mismatched, (
        "the destructuring order no longer matches the request order; every lane after "
        f"the first mismatch receives another lane's payload: {mismatched[:4]}"
    )


def test_every_fetched_key_is_assigned_onto_state():
    source = _source()
    block = _load_core_block(source)
    assigned = set(re.findall(r"state\.(\w+)\s*=\s*\1\b", block))
    missing = [key for key in _requested_keys(block) if key not in assigned]
    assert not missing, f"fetched but never stored on state: {missing}"


def test_every_fetched_key_has_a_page_gate():
    """`request` spreads PAGE_FETCHES[key]; a missing entry throws and kills the load."""
    source = _source()
    gated = _page_fetch_keys(source)
    missing = [key for key in _requested_keys(_load_core_block(source)) if key not in gated]
    assert not missing, f"no PAGE_FETCHES entry (onPage would spread undefined): {missing}"


def test_the_crypto_page_fetches_the_crypto_lanes():
    """A guard on the guard: the checks above pass trivially if nothing is wired."""
    source = _source()
    start = source.index("const PAGE_FETCHES = {")
    end = source.index("};", start)
    block = source[start:end]
    for key in ("cryptoOverview", "cryptoBoard", "cryptoRegime", "cryptoLiquidations", "cryptoNews"):
        match = re.search(rf"^\s*{key}\s*:\s*\[([^\]]*)\]", block, re.M)
        assert match, f"{key} has no PAGE_FETCHES entry"
        assert '"crypto"' in match.group(1), f"{key} is not fetched on the crypto page"


def test_the_live_card_lanes_all_have_a_five_second_loop():
    """마크가격은 실시간 소스다. 5초 루프가 없으면 15분 주기에만 값이 바뀐다.

    그러면 계기판도 깜빡임도 돌 일이 없어서 화면이 정지 화면처럼 보인다 —
    에러가 아니라 "안 움직인다"로만 나타난다(실측: 미국 야간 카드가 그랬다).
    """
    source = _source()
    for lane in ("krOvernight", "cryptoOverview", "usOvernight"):
        assert f"onPage(...PAGE_FETCHES.{lane})" in source, f"{lane}에 5초 루프가 없다"
