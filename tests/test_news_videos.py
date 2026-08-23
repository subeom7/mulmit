"""뉴스 영상 lane — 권리 조건이 문서가 아니라 코드로 지켜지는지.

이 lane의 조건 세 가지는 전부 기계로 확인할 수 있는 성질이다:

* 누르기 전에는 유튜브로 요청이 나가지 않는다 → payload에 이미지 URL이 없다.
* 저장은 30일을 넘기지 않는다 → 오래된 항목은 읽을 때 떨어진다.
* 채널은 ID로 못 박는다 → 핸들이 채널을 식별하지 못한다는 실측의 귀결.

넷째는 균형이다. 언어로만 번갈아 뽑던 판이 업로드 잦은 채널에 슬롯을
빼앗겼다(실측: 한국어 6칸 중 YTN이 4칸). 못 박은 채널이 다 보여야 한다.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app import news_videos
from app.providers.base import DataUnavailable
from app.providers.youtube import NEWS_CHANNELS, NewsChannel, parse_uploads, parse_uploads_playlists

KO = NewsChannel("UC_ko", "한국채널", "ko")


def _item(video_id: str, title: str, published: str, *, owner: str | None = None) -> dict:
    return {
        "snippet": {
            "title": title,
            "publishedAt": published,
            "channelTitle": "채널",
            "videoOwnerChannelTitle": owner,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
            "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/x/hqdefault.jpg"}},
        }
    }


def test_no_image_url_survives_into_the_payload():
    """썸네일 하나가 곧 클릭 전 구글 요청이다 — 이 lane의 전제가 깨진다."""
    videos = parse_uploads({"items": [_item("abc", "제목", "2026-08-23T00:00:00Z")]}, KO)

    assert videos, "파싱이 아무것도 남기지 않았다"
    blob = json.dumps(videos)
    assert "ytimg" not in blob and "thumbnail" not in blob.lower()
    assert not any("http" in str(value) for key, value in videos[0].items() if key != "watch_url")


def test_deleted_and_private_placeholders_are_dropped():
    """업로드 플레이리스트는 지워진 영상의 자리를 그대로 남긴다 — 죽은 링크가 된다."""
    raw = {"items": [
        _item("a", "살아있는 제목", "2026-08-23T00:00:00Z"),
        _item("b", "Deleted video", "2026-08-22T00:00:00Z"),
        _item("c", "Private video", "2026-08-21T00:00:00Z"),
    ]}

    assert [video["video_id"] for video in parse_uploads(raw, KO)] == ["a"]


def test_channel_name_whitespace_is_trimmed():
    """유튜브는 " YTN"처럼 앞 공백을 붙여 준다."""
    videos = parse_uploads({"items": [_item("a", "제목", "2026-08-23T00:00:00Z", owner=" YTN ")]}, KO)

    assert videos[0]["channel"] == "YTN"


def test_every_pinned_channel_appears_when_all_are_uploading():
    """언어로만 번갈아 뽑으면 업로드 잦은 채널이 슬롯을 독식한다."""
    by_channel = {
        channel.channel_id: [
            {"video_id": f"{channel.channel_id}-{index}", "lang": channel.lang,
             "published_at": f"2026-08-2{9 - index}T00:00:00Z"}
            for index in range(4)
        ]
        for channel in NEWS_CHANNELS
    }

    picked = news_videos._interleave(by_channel, 12)

    per_channel = dict.fromkeys(by_channel, 0)
    for video in picked:
        per_channel[video["video_id"].rsplit("-", 1)[0]] += 1
    assert len(picked) == 12
    assert min(per_channel.values()) >= 1, f"채널 하나가 통째로 빠졌다: {per_channel}"
    assert max(per_channel.values()) - min(per_channel.values()) <= 1, per_channel
    languages = {video["lang"] for video in picked}
    assert languages == {"ko", "en"}


def test_a_quiet_channel_does_not_hold_a_slot_empty():
    """한 채널이 한 편뿐이어도 나머지 자리는 채워져야 한다."""
    by_channel = {
        NEWS_CHANNELS[0].channel_id: [
            {"video_id": "solo", "lang": NEWS_CHANNELS[0].lang, "published_at": "2026-08-23T00:00:00Z"}
        ],
        NEWS_CHANNELS[2].channel_id: [
            {"video_id": f"many-{index}", "lang": NEWS_CHANNELS[2].lang,
             "published_at": f"2026-08-2{9 - index}T00:00:00Z"}
            for index in range(4)
        ],
    }

    picked = news_videos._interleave(by_channel, 5)

    assert [video["video_id"] for video in picked][0] == "solo"
    assert len(picked) == 5, "조용한 채널이 남은 자리를 붙잡고 있었다"


def test_stored_items_past_the_retention_limit_are_not_served():
    """약관의 30일 상한. ingest가 멈춰도 블롭이 스스로 비어야 한다."""
    now = dt.datetime(2026, 8, 23, tzinfo=dt.UTC)
    fresh = (now - dt.timedelta(days=29)).isoformat().replace("+00:00", "Z")
    stale = (now - dt.timedelta(days=31)).isoformat().replace("+00:00", "Z")

    kept = news_videos._within_retention(
        [{"video_id": "new", "stored_at": fresh},
         {"video_id": "old", "stored_at": stale},
         {"video_id": "undated"}],
        now,
    )

    assert [video["video_id"] for video in kept] == ["new"]


def test_retention_limit_matches_the_terms():
    assert news_videos.RETENTION_DAYS <= 30


def test_serving_refuses_rather_than_showing_expired_rows(monkeypatch):
    """만료된 블롭은 조용히 오래된 목록을 내보이는 대신 실패한다."""
    monkeypatch.setattr(news_videos.config, "YOUTUBE_ENABLED", True)
    monkeypatch.setattr(news_videos.config, "YOUTUBE_API_KEY", "k")
    stale = (news_videos._now() - dt.timedelta(days=40)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(
        news_videos.store, "load_report",
        lambda *_a, **_k: {"videos": [{"video_id": "old", "stored_at": stale}]},
    )

    with pytest.raises(DataUnavailable):
        news_videos.get_videos()


def test_the_lane_is_closed_without_a_key():
    """게이트는 fail-closed다 — 키가 없으면 열리지 않는다."""
    with pytest.raises(news_videos.NewsVideosDisabled):
        news_videos.get_videos()


def test_channels_are_pinned_by_id_not_by_handle():
    """핸들은 채널을 식별하지 못한다: @KBSnews는 개인 채널로 풀린다."""
    for channel in NEWS_CHANNELS:
        assert channel.channel_id.startswith("UC"), channel
        assert len(channel.channel_id) == 24, channel
        assert "@" not in channel.channel_id
        assert channel.lang in ("ko", "en")
    assert len({channel.channel_id for channel in NEWS_CHANNELS}) == len(NEWS_CHANNELS)


def test_uploads_playlist_is_read_from_the_api_not_guessed():
    """UC→UU 치환은 문서화된 규칙이 아니다 — 응답에서 읽는다."""
    playlists = parse_uploads_playlists(
        {"items": [{"id": "UC_ko", "contentDetails": {"relatedPlaylists": {"uploads": "UU_ko"}}},
                   {"id": "UC_bad", "contentDetails": {}}]}
    )

    assert playlists == {"UC_ko": "UU_ko"}


# --- 프런트엔드: 파사드가 실제로 파사드인가 ---------------------------------

STATIC = __import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "static"


def test_the_landing_page_holds_no_youtube_url_at_all():
    """마크업에 유튜브 URL이 하나라도 있으면 그건 파사드가 아니다.

    <img src="i.ytimg.com/...">나 미리 박아 둔 <iframe> 하나면 페이지를 여는
    것만으로 구글에 요청이 나간다. 이 lane의 약속이 정확히 그 반대다.
    """
    markup = (STATIC / "landing.html").read_text(encoding="utf-8")

    for host in ("youtube.com", "youtu.be", "ytimg.com", "youtube-nocookie.com", "googlevideo.com"):
        assert host not in markup, f"landing.html이 {host}를 직접 물고 있다"


def test_the_iframe_is_built_only_inside_the_click_handler():
    """유튜브 주소가 등장하는 곳은 클릭 핸들러 안뿐이어야 한다."""
    script = (STATIC / "monitor.js").read_text(encoding="utf-8")
    start = script.index("function renderNewsVideos()")
    end = script.index("function renderCryptoRegime()")
    lane = script[start:end]

    assert "youtube-nocookie.com/embed/" in lane
    handler = lane[lane.index('play.addEventListener("click"'):]
    assert "youtube-nocookie.com/embed/" in handler, "임베드 주소가 핸들러 밖에서 만들어진다"
    # 목록을 그리는 동안 이미지를 만들면 그 순간 요청이 나간다.
    listing = lane[: lane.index('play.addEventListener("click"')]
    assert "createElement(\"img\")" not in listing and "ytimg" not in listing


def test_the_embed_uses_the_privacy_enhanced_host():
    script = (STATIC / "monitor.js").read_text(encoding="utf-8")
    assert "www.youtube-nocookie.com/embed/" in script
    assert "www.youtube.com/embed/" not in script


def test_the_player_is_not_shrunk_below_the_size_the_terms_require():
    """약관은 플레이어를 200x200 미만으로 두지 못하게 한다."""
    css = (STATIC / "monitor.css").read_text(encoding="utf-8")
    rule = css[css.index(".news-videos .nvid-frame"):]
    rule = rule[: rule.index("}")]

    assert "min-height: 200px" in rule
    assert "width: 100%" in rule
