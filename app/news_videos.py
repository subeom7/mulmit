"""시장 뉴스 영상 lane — 못 박은 뉴스 채널의 최근 업로드.

표시하는 것은 **제목 + 채널명 + 게시시각 + 유튜브 링크**뿐이다. 썸네일은
일부러 가져오지 않는다: 이미지를 부르는 순간 독자가 아무것도 누르기 전에
구글로 요청이 나가기 때문이고, 이 lane의 설계 전체가 "누르기 전에는 구글로
아무 요청도 가지 않는다"에 걸려 있다(등록부 §3.28, `DS-2026-020`).

수집은 ingest 전용이고 web은 저장 블롭만 읽는다. 채널은 **ID로** 못 박는다 —
핸들은 채널을 식별하지 못한다(providers/youtube.py의 실측 참조).

약관의 30일 보관 한도는 문서가 아니라 코드로 지킨다: 저장 시각이 30일을 넘긴
항목은 읽을 때 떨어져 나간다. 인제스트가 멈춰도 블롭이 스스로 비는 쪽이,
"갱신하고 있을 것"이라는 가정보다 안전하다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, store
from .providers.youtube import (
    NEWS_CHANNELS,
    YOUTUBE_POLICY_URL,
    YOUTUBE_PROVIDER_ID,
    YOUTUBE_PUBLISHER,
    YOUTUBE_SITE_URL,
    YOUTUBE_TERMS_URL,
    YouTubeProvider,
)

log = logging.getLogger(__name__)

CACHE_KEY = "news_videos_v1"
PER_CHANNEL = 4          # 채널당 이만큼 읽어서
MAX_VIDEOS = 12          # 언어별로 번갈아 이만큼 남긴다
RETENTION_DAYS = 30      # 약관 상한 그대로. 넘기지 않는다.

ATTRIBUTION = "Video listings from YouTube"
ATTRIBUTION_KO = "영상 목록 출처: YouTube"

BASIS_KO = (
    "못 박은 뉴스 채널의 최근 업로드 목록입니다. 제목·채널·게시시각만 가져오며, "
    "썸네일은 부르지 않습니다 — 누르기 전에는 유튜브로 아무 요청도 나가지 "
    "않습니다. 재생을 누르면 그때 유튜브가 로드되고 유튜브의 쿠키·정책이 "
    "적용됩니다. 영상의 내용은 각 채널의 것이며 이 사이트의 수치와는 무관합니다."
)
BASIS_EN = (
    "Recent uploads from a pinned set of news channels. Titles, channel names and "
    "publication times only — no thumbnails are fetched, so nothing reaches YouTube "
    "until you ask for it. Pressing play loads YouTube at that moment, under "
    "YouTube's own cookies and policies. The videos are their channels' content and "
    "carry none of this site's figures."
)


class NewsVideosDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    """서빙 게이트. 저장된 목록을 내보내는 데 키는 필요 없다.

    키까지 요구하면 web 컨테이너에서 lane이 통째로 잠긴다 — 키는 ingest에만
    주기 때문이다(docker-compose.yml의 x-app 대 ingest 블록). 그러면 수집은
    멀쩡히 되는데 화면에서는 섹션이 조용히 사라진다.
    """
    if not config.YOUTUBE_ENABLED:
        raise NewsVideosDisabled("disabled")


def _require_key() -> None:
    """수집 게이트. 유튜브를 부르는 쪽에만 키가 있으면 된다."""
    _require_lane()
    if not config.YOUTUBE_API_KEY:
        raise NewsVideosDisabled("no api key")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stamp(moment: dt.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _parse(stamp: Any) -> dt.datetime | None:
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _interleave(by_channel: dict[str, list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    """채널을 돌아가며 한 편씩, 언어를 번갈아 뽑는다.

    언어로만 번갈아 뽑으면 업로드가 잦은 채널이 슬롯을 독식한다(실측: YTN이
    한국어 6칸 중 4칸, 블룸버그가 영어 6칸 중 4칸). 못 박은 채널이 넷인데 둘만
    보이면 못 박은 의미가 없으므로, 채널 단위로 돌린다.
    """
    for videos in by_channel.values():
        videos.sort(key=lambda video: video.get("published_at") or "", reverse=True)

    # ko, en, ko, en... 순으로 채널을 배열한 뒤 그 순서로 한 바퀴씩 돈다.
    queues = {
        lang: [
            channel.channel_id
            for channel in NEWS_CHANNELS
            if channel.lang == lang and by_channel.get(channel.channel_id)
        ]
        for lang in ("ko", "en")
    }
    order: list[str] = []
    while any(queues.values()):
        for lang in ("ko", "en"):
            if queues[lang]:
                order.append(queues[lang].pop(0))

    picked: list[dict[str, Any]] = []
    while order and len(picked) < limit:
        remaining: list[str] = []
        for channel_id in order:
            if len(picked) >= limit:
                remaining.append(channel_id)
                continue
            queue = by_channel.get(channel_id) or []
            if queue:
                picked.append(queue.pop(0))
                if queue:
                    remaining.append(channel_id)
        if not remaining:
            break
        order = remaining
    return picked


def refresh(provider: YouTubeProvider | None = None) -> dict:
    """채널별 업로드 플레이리스트를 걷어 블롭을 갈아끼운다.

    `channels.list`도 `playlistItems.list`도 각 1유닛이라 하루 10,000 예산에서
    한 사이클이 5유닛이다. 100회/일짜리 `search.list` 버킷은 건드리지 않는다.
    """
    _require_key()
    provider = provider or YouTubeProvider(
        config.YOUTUBE_API_KEY, timeout=config.YOUTUBE_TIMEOUT
    )

    playlists = provider.fetch_uploads_playlists(NEWS_CHANNELS)
    now = _now()
    stored_at = _stamp(now)

    by_channel: dict[str, list[dict[str, Any]]] = {}
    silent: list[str] = []
    for channel in NEWS_CHANNELS:
        playlist_id = playlists.get(channel.channel_id)
        if not playlist_id:
            # 채널이 사라졌거나 ID가 틀렸다. 다른 채널까지 죽이지 않는다.
            silent.append(channel.name)
            log.warning("youtube: no uploads playlist for %s (%s)", channel.name, channel.channel_id)
            continue
        try:
            videos = provider.fetch_uploads(playlist_id, channel, limit=PER_CHANNEL)
        except Exception as exc:  # noqa: BLE001 - 한 채널의 실패가 lane을 죽이지 않는다
            silent.append(channel.name)
            log.warning("youtube: %s failed: %s", channel.name, exc)
            continue
        for video in videos:
            by_channel.setdefault(channel.channel_id, []).append({**video, "stored_at": stored_at})

    picked = _interleave(by_channel, MAX_VIDEOS)
    if not picked:
        from .providers.base import DataUnavailable

        raise DataUnavailable("youtube returned no usable videos")

    payload = {
        "generated_at": stored_at,
        "videos": picked,
        "count": len(picked),
        "silent": silent,
        "retention_days": RETENTION_DAYS,
        "channels": [
            {"name": channel.name, "lang": channel.lang, "channel_id": channel.channel_id}
            for channel in NEWS_CHANNELS
        ],
        "basis_ko": BASIS_KO,
        "basis_en": BASIS_EN,
        "attribution": {
            "required": True,
            "text": ATTRIBUTION,
            "text_ko": ATTRIBUTION_KO,
            "url": YOUTUBE_SITE_URL,
        },
        "source": {
            "provider": YOUTUBE_PROVIDER_ID,
            "publisher": YOUTUBE_PUBLISHER,
            "publisher_url": YOUTUBE_SITE_URL,
            "terms_url": YOUTUBE_TERMS_URL,
            "privacy_url": YOUTUBE_POLICY_URL,
        },
        "rights": {"status": "approved", "notice": ATTRIBUTION},
    }
    store.save_report(CACHE_KEY, payload)
    return {"kept": len(picked), "silent": silent}


def _within_retention(videos: list[Any], now: dt.datetime) -> list[dict[str, Any]]:
    cutoff = now - dt.timedelta(days=RETENTION_DAYS)
    kept: list[dict[str, Any]] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        stored = _parse(video.get("stored_at"))
        # 저장 시각이 없으면 언제 받았는지 증명할 수 없다 — 보관 한도를 지켰다고
        # 말할 수 없으므로 내보내지 않는다.
        if stored is None or stored < cutoff:
            continue
        kept.append(video)
    return kept


def get_videos() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 유튜브를 호출하지 않는다."""
    _require_lane()
    from .providers.base import DataUnavailable

    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 4)
    if cached is None:
        raise DataUnavailable("news videos not collected yet")

    fresh = _within_retention(cached.get("videos") or [], _now())
    if not fresh:
        raise DataUnavailable("stored videos passed the retention limit")
    return {**cached, "videos": fresh, "count": len(fresh)}
