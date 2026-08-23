"""홈 피드는 종류를 한 바퀴씩 돌며 뽑는다 — 한 소스가 화면을 쓸어 가지 않게.

순수 최신순으로 자르면 가장 자주 터지는 소스가 자리를 다 가져간다. 실측
2026-08-23: 홈 30칸 중 12칸이 국내 주요사항보고였고 대부분 이름이 낯선
소형주였다. 같은 화면에서 연금 공시는 0칸이었다.

개수만 줄이는 것으로는 못 고친다 — 비율이 그대로라 짧아진 소형주 목록이 될
뿐이다. 그래서 자르는 규칙 자체를 바꿨고, 이 파일이 그 규칙을 지킨다.
"""

from __future__ import annotations

from collections import Counter

from app.signal_feed import MAX_ITEMS, _balanced


def _feed() -> list[dict]:
    """실제로 관측된 구성(2026-08-23 라이브)."""
    counts = {"kr_material": 12, "news": 8, "kr_press": 4, "us_8k": 3, "kr_holdings": 3}
    items = []
    hour = 100
    for kind, many in counts.items():
        for _ in range(many):
            hour -= 1
            items.append({"kind": kind, "at": f"2026-08-23T{hour:04d}"})
    items.sort(key=lambda item: item["at"], reverse=True)
    return items


def test_no_source_takes_more_than_a_quarter_of_the_home_widget():
    kept = _balanced(_feed(), MAX_ITEMS)
    share = Counter(item["kind"] for item in kept)

    assert len(kept) == MAX_ITEMS
    assert share["kr_material"] <= MAX_ITEMS // 4, share
    # 그리고 조용한 소스도 자리를 얻는다 — 예전에는 0칸이었다.
    assert len(share) == 5, share
    assert min(share.values()) >= 3, share


def test_the_newest_item_is_still_at_the_top():
    """균형을 맞추느라 화면 위쪽이 낡으면 안 된다."""
    items = _feed()
    kept = _balanced(items, MAX_ITEMS)

    assert kept[0] is items[0]
    # 각 종류의 1등이 먼저 오므로, 앞쪽은 서로 다른 종류다.
    assert len({item["kind"] for item in kept[:5]}) == 5


def test_the_dedicated_page_hides_nothing():
    """/news는 다 보여 주는 것이 목적이다."""
    items = _feed()

    assert _balanced(items, 120) and len(_balanced(items, 120)) == len(items)
    assert Counter(i["kind"] for i in _balanced(items, 120)) == Counter(i["kind"] for i in items)


def test_a_thin_day_does_not_shrink_the_widget():
    """소스가 하나뿐이어도 있는 만큼은 채운다 — 빈 화면보다 낫다."""
    only_news = [{"kind": "news", "at": f"2026-08-23T00{i:02d}"} for i in range(9)]

    assert len(_balanced(only_news, MAX_ITEMS)) == 9


def test_ordering_is_stable_for_the_same_input():
    items = _feed()
    assert [i["at"] for i in _balanced(items, MAX_ITEMS)] == [i["at"] for i in _balanced(items, MAX_ITEMS)]
