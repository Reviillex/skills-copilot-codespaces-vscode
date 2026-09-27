"""YouTube Data API v3: find what performs and what the audience asks for.

Views per day says what worked; comments say what people still want. Commenter
names are dropped at parse time: only the text reaches disk and the models.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from .config import YouTubeConfig

API = "https://www.googleapis.com/youtube/v3"


class YouTubeError(RuntimeError):
    pass


@dataclass
class Video:
    id: str
    title: str
    channel: str
    published: str  # RFC 3339
    views: int
    likes: int
    comments: int
    duration_s: int

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    def age_days(self, now: dt.datetime) -> float:
        published = dt.datetime.fromisoformat(self.published.replace("Z", "+00:00"))
        return max((now - published).total_seconds() / 86400, 1.0)

    def views_per_day(self, now: dt.datetime) -> float:
        return self.views / self.age_days(now)

    @property
    def comments_per_1k_views(self) -> float:
        return 1000 * self.comments / self.views if self.views else 0.0


@dataclass
class Comment:
    video_id: str
    text: str
    likes: int


def _get(endpoint: str, params: dict[str, str]) -> dict:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise YouTubeError("Set YOUTUBE_API_KEY (Google Cloud console, YouTube Data API v3).")
    url = f"{API}/{endpoint}?{urllib.parse.urlencode({**params, 'key': key})}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def parse_duration(iso: str) -> int:
    """ISO 8601 duration (PT1H2M3S) -> seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def search_video_ids(query: str, cfg: YouTubeConfig, now: dt.datetime | None = None) -> list[str]:
    """Most-viewed videos for ``query`` published in the last ``cfg.days`` days (100 quota units)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    after = (now - dt.timedelta(days=cfg.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _get("search", {
        "part": "snippet", "q": query, "type": "video", "order": "viewCount",
        "publishedAfter": after, "regionCode": cfg.region, "relevanceLanguage": cfg.language,
        "maxResults": str(min(cfg.max_videos, 50)),
    })
    return [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]


def parse_videos(data: dict) -> list[Video]:
    videos = []
    for item in data.get("items", []):
        sn, st = item.get("snippet", {}), item.get("statistics", {})
        videos.append(Video(
            id=item["id"], title=sn.get("title", ""), channel=sn.get("channelTitle", ""),
            published=sn.get("publishedAt", ""), views=int(st.get("viewCount", 0)),
            likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)),
            duration_s=parse_duration(item.get("contentDetails", {}).get("duration", "")),
        ))
    return videos


def video_details(ids: list[str]) -> list[Video]:
    if not ids:
        return []
    return parse_videos(_get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}))


def parse_comments(data: dict, video_id: str) -> list[Comment]:
    out = []
    for item in data.get("items", []):
        sn = item["snippet"]["topLevelComment"]["snippet"]
        text = " ".join((sn.get("textOriginal") or sn.get("textDisplay") or "").split())
        if text:
            out.append(Comment(video_id=video_id, text=text, likes=int(sn.get("likeCount", 0))))
    return out


def top_comments(video_id: str, n: int) -> list[Comment]:
    """Most relevant top-level comments; [] when comments are disabled."""
    try:
        data = _get("commentThreads", {
            "part": "snippet", "videoId": video_id, "order": "relevance",
            "textFormat": "plainText", "maxResults": str(min(n, 100)),
        })
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):  # commentsDisabled / video gone
            return []
        raise
    return parse_comments(data, video_id)


def rank_by_momentum(videos: list[Video], now: dt.datetime | None = None) -> list[Video]:
    now = now or dt.datetime.now(dt.timezone.utc)
    return sorted(videos, key=lambda v: v.views_per_day(now), reverse=True)


def to_json(items: list) -> str:
    return json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2)
