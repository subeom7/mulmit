"""YouTube — recent uploads from a pinned set of news channels (keyed, ingest-only).

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.28, `DS-2026-020`): YouTube
publishes an embed mechanism itself and each uploader decides whether embedding
is on, so this is not us taking something — it is us using what is offered. The
conditions read on 2026-08-23: search results may be stored temporarily and no
longer than thirty days then refreshed or deleted, YouTube must be named as the
source, and our own figures must not read as though they came from YouTube.

Three things measured on 2026-08-23 shape this module:

1. **Handles do not identify a channel.** `@KBSnews` resolves to a personal
   channel named "byung joo lee" and `@wowtv` to two travel videos from 2013,
   not the Korean business broadcaster. Channels are therefore pinned by id.
   Getting the wrong broadcaster's video onto the home page is the worst way
   this could fail, and a handle is exactly how that happens.

2. **Uploads cost one unit, search costs a whole bucket.** `search.list` has its
   own quota of 100 calls a day, while `playlistItems.list` and `channels.list`
   draw one unit each from the 10,000-a-day pool. Reading each channel's uploads
   playlist keeps the search bucket entirely unused.

3. **Thumbnail URLs travel; thumbnail bytes do not.** Re-hosting the images on
   our own server would be the cleanest thing for privacy, but section III.E.1.a
   of the Developer Policies forbids downloading, caching or storing copies of
   YouTube content without written approval, so the browser loads them from
   Google's CDN. That costs the viewer an IP address — and measurably nothing
   else: `i.ytimg.com` returned no `Set-Cookie` at all on 2026-08-23, unlike the
   player, which sets `VISITOR_INFO1_LIVE`, `YSC`, `GPS` and DoubleClick `IDE`.
   The player still loads only on a click.

4. **Only the 16:9 sizes are usable.** `high` (480x360) and `standard` (640x480)
   are 4:3 and letterbox a widescreen video with black bars; `medium` (320x180)
   and `maxres` (1280x720) are the real aspect. `maxres` is often absent, so it
   is carried when present and never depended on.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .base import DataUnavailable, RateLimited

YOUTUBE_PROVIDER_ID = "youtube"
YOUTUBE_PUBLISHER = "YouTube"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_SITE_URL = "https://www.youtube.com/"
YOUTUBE_TERMS_URL = "https://www.youtube.com/t/terms"
YOUTUBE_POLICY_URL = "https://policies.google.com/privacy"
WATCH_URL = "https://www.youtube.com/watch?v="

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"


@dataclass(frozen=True)
class NewsChannel:
    """A channel pinned by id, with the language its audience reads."""

    channel_id: str
    name: str
    lang: str  # "ko" | "en"


# Verified 2026-08-23 by resolving the real channel and reading its recent
# uploads. 한국경제TV was left out on purpose: its feed mixes market coverage
# with "월요일 공략할 TOP4" tip content and a knee-arthritis health magazine,
# and neither belongs beside sourced numbers.
NEWS_CHANNELS: tuple[NewsChannel, ...] = (
    NewsChannel("UCbMjg2EvXs_RUGW-KrdM3pw", "SBS Biz 뉴스", "ko"),
    NewsChannel("UChlgI3UHCOnwUGzWzbJ3H5w", "YTN", "ko"),
    NewsChannel("UCrp_UI8XtuYfpiqluWLD7Lw", "CNBC Television", "en"),
    NewsChannel("UCIALMKvObZNtJ6AmdCLP7Lg", "Bloomberg Television", "en"),
)

Transport = Callable[[str, float], Any]


def _default_transport(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _iso(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_uploads_playlists(raw: Any) -> dict[str, str]:
    """channelId -> uploads playlist id, for the channels the API recognised."""
    if not isinstance(raw, dict):
        raise DataUnavailable("YouTube returned a non-object channels payload")
    playlists: dict[str, str] = {}
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
        related = details.get("relatedPlaylists") if isinstance(details.get("relatedPlaylists"), dict) else {}
        channel_id, uploads = item.get("id"), related.get("uploads")
        if isinstance(channel_id, str) and isinstance(uploads, str) and uploads:
            playlists[channel_id] = uploads
    return playlists


def _thumbnails(raw: Any) -> list[dict[str, Any]]:
    """16:9인 크기만, 좁은 것부터. 4:3짜리는 검은 띠가 생겨 쓰지 않는다."""
    if not isinstance(raw, dict):
        return []
    sizes: list[dict[str, Any]] = []
    for key in ("medium", "maxres"):
        entry = raw.get(key)
        if not isinstance(entry, dict):
            continue
        url, width = entry.get("url"), entry.get("width")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        sizes.append({"url": url, "width": int(width) if isinstance(width, int) else 0})
    return sorted(sizes, key=lambda size: size["width"])


def parse_uploads(raw: Any, channel: NewsChannel) -> list[dict[str, Any]]:
    """Recent videos as title, channel, time and watch link — no image, by design."""
    if not isinstance(raw, dict):
        raise DataUnavailable("YouTube returned a non-object playlistItems payload")
    videos: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        resource = snippet.get("resourceId") if isinstance(snippet.get("resourceId"), dict) else {}
        video_id = resource.get("videoId")
        title = snippet.get("title")
        if not isinstance(video_id, str) or not isinstance(title, str) or not title.strip():
            continue
        # Deleted and private entries keep their slot in an uploads playlist
        # with a placeholder title; they would render as a dead link.
        if title.strip() in ("Deleted video", "Private video"):
            continue
        videos.append({
            "video_id": video_id,
            "thumbnails": _thumbnails(snippet.get("thumbnails")),
            "title": title.strip(),
            # 유튜브가 돌려주는 채널명에는 앞뒤 공백이 붙어 오기도 한다(" YTN").
            "channel": str(
                snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle") or channel.name
            ).strip() or channel.name,
            "channel_id": channel.channel_id,
            "lang": channel.lang,
            "published_at": _iso(snippet.get("publishedAt")),
            "watch_url": f"{WATCH_URL}{video_id}",
        })
    return videos


class YouTubeProvider:
    """Reads uploads playlists. Never touches the search quota."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise DataUnavailable("YouTube API key is not configured")
        self._key = key
        self._transport = transport or _default_transport
        self._timeout = timeout

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode({"key": self._key, **params})
        try:
            return self._transport(f"{YOUTUBE_API_BASE}/{endpoint}?{query}", self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # 403 is how this API reports both a bad key and an exhausted
                # quota; either way there is nothing to retry into today.
                raise RateLimited("YouTube rejected the request (key or quota)") from exc
            raise DataUnavailable(f"YouTube returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise DataUnavailable(f"YouTube request failed: {exc}") from exc

    def fetch_uploads_playlists(self, channels: tuple[NewsChannel, ...]) -> dict[str, str]:
        """One call for every channel — ids are comma separated."""
        if not channels:
            return {}
        raw = self._get("channels", {
            "part": "contentDetails",
            "id": ",".join(channel.channel_id for channel in channels),
            "maxResults": len(channels),
        })
        return parse_uploads_playlists(raw)

    def fetch_uploads(self, playlist_id: str, channel: NewsChannel, *, limit: int = 6) -> list[dict[str, Any]]:
        raw = self._get("playlistItems", {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": max(1, min(50, limit)),
        })
        return parse_uploads(raw, channel)
