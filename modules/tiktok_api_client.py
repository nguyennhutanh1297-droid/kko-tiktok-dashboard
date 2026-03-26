"""
TikTok API v2 client wrapper.
Base URL: https://open.tiktokapis.com/v2/
All methods accept a valid access_token and return parsed dicts.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

BASE_URL = "https://open.tiktokapis.com/v2"
DEFAULT_TIMEOUT = 20


def _get(endpoint: str, access_token: str, params: dict | None = None) -> dict:
    """Generic GET with Bearer auth."""
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, headers=headers, params=params or {}, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error", {}).get("code", "ok") != "ok":
        raise ValueError(f"TikTok API error: {data['error']}")
    return data


def _post(endpoint: str, access_token: str, payload: dict | None = None) -> dict:
    """Generic POST with Bearer auth."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{endpoint}"
    resp = requests.post(url, headers=headers, json=payload or {}, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error", {}).get("code", "ok") != "ok":
        raise ValueError(f"TikTok API error: {data['error']}")
    return data


# ── User Info ──────────────────────────────────────────────────────────────────

USER_INFO_FIELDS = (
    "open_id,union_id,avatar_url,display_name,"
    "follower_count,following_count,likes_count,video_count"
)


def get_user_info(access_token: str) -> dict:
    """
    Fetch authenticated user's profile.
    Returns: {open_id, display_name, avatar_url, follower_count, ...}
    """
    data = _get("/user/info/", access_token, params={"fields": USER_INFO_FIELDS})
    return data.get("data", {}).get("user", {})


# ── Video List ─────────────────────────────────────────────────────────────────

VIDEO_LIST_FIELDS = "id,title,create_time,cover_image_url,share_url,duration,height,width"


def get_video_list(
    access_token: str,
    max_count: int = 20,
    cursor: Optional[int] = None,
) -> tuple[list[dict], bool, int]:
    """
    Fetch list of user's videos.
    Returns: (videos, has_more, next_cursor)
    """
    payload: dict = {
        "max_count": min(max_count, 20),  # API max is 20
        "fields": VIDEO_LIST_FIELDS,
    }
    if cursor is not None:
        payload["cursor"] = cursor

    data = _post("/video/list/", access_token, payload)
    body = data.get("data", {})
    videos = body.get("videos", [])
    has_more = body.get("has_more", False)
    next_cursor = body.get("cursor", 0)
    return videos, has_more, next_cursor


def get_all_videos(access_token: str, limit: int = 50) -> list[dict]:
    """Paginate through video list, up to `limit` videos."""
    all_videos: list[dict] = []
    cursor = None
    while len(all_videos) < limit:
        batch, has_more, next_cursor = get_video_list(
            access_token, max_count=20, cursor=cursor
        )
        all_videos.extend(batch)
        if not has_more or not batch:
            break
        cursor = next_cursor
    return all_videos[:limit]


# ── Video Query (stats) ────────────────────────────────────────────────────────

VIDEO_QUERY_FIELDS = (
    "id,title,create_time,cover_image_url,share_url,"
    "view_count,like_count,comment_count,share_count,play_count"
)


def get_video_stats(access_token: str, video_ids: list[str]) -> list[dict]:
    """
    Fetch statistics for specific video IDs (up to 20 per call).
    Returns list of video stat dicts.
    """
    if not video_ids:
        return []

    all_stats: list[dict] = []
    # TikTok allows max 20 video IDs per query
    for i in range(0, len(video_ids), 20):
        chunk = video_ids[i : i + 20]
        payload = {
            "filters": {"video_ids": chunk},
            "fields": VIDEO_QUERY_FIELDS,
        }
        data = _post("/video/query/", access_token, payload)
        videos = data.get("data", {}).get("videos", [])
        all_stats.extend(videos)
        if i + 20 < len(video_ids):
            time.sleep(0.3)  # be polite to rate limits

    return all_stats


# ── Convenience: fetch videos + stats in one call ──────────────────────────────

def get_videos_with_stats(access_token: str, limit: int = 50) -> list[dict]:
    """
    Fetch up to `limit` videos and enrich them with stats.
    Returns merged list sorted by create_time desc.
    """
    videos = get_all_videos(access_token, limit=limit)
    if not videos:
        return []

    video_ids = [v["id"] for v in videos]
    stats_list = get_video_stats(access_token, video_ids)

    # Merge by id
    stats_map = {s["id"]: s for s in stats_list}
    enriched = []
    for v in videos:
        merged = {**v, **stats_map.get(v["id"], {})}
        # Compute engagement rate = (likes + comments + shares) / views * 100
        views = merged.get("view_count") or merged.get("play_count") or 0
        interactions = (
            (merged.get("like_count") or 0)
            + (merged.get("comment_count") or 0)
            + (merged.get("share_count") or 0)
        )
        merged["engagement_rate"] = round(interactions / views * 100, 2) if views else 0
        enriched.append(merged)

    enriched.sort(key=lambda v: v.get("create_time", 0), reverse=True)
    return enriched
