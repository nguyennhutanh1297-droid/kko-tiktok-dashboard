"""
Data sync & cache layer.
Fetches data from TikTok API and stores per-channel JSON cache.
Cache is considered fresh for 1 hour; older cache triggers re-sync.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .tiktok_auth import get_valid_token, list_connected_channels, get_channel_display_name
from .tiktok_api_client import get_user_info, get_videos_with_stats

CACHE_DIR = Path(__file__).parent.parent / "data" / "tiktok_cache"
CACHE_TTL_SECONDS = 3600  # 1 hour


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_path(channel_id: str, kind: str) -> Path:
    """Return path for a channel's cache file. kind = 'profile' | 'videos'"""
    return CACHE_DIR / f"{channel_id}_{kind}.json"


def _read_cache(channel_id: str, kind: str) -> dict | None:
    path = _cache_path(channel_id, kind)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_cache(channel_id: str, kind: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload["_synced_at"] = int(time.time())
    with open(_cache_path(channel_id, kind), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _is_stale(cached: dict | None) -> bool:
    if cached is None:
        return True
    synced_at = cached.get("_synced_at", 0)
    return (int(time.time()) - synced_at) > CACHE_TTL_SECONDS


# ── Sync ───────────────────────────────────────────────────────────────────────

def sync_channel(channel_id: str, force: bool = False) -> dict:
    """
    Sync a single channel: fetch profile + videos with stats.
    Uses cache if fresh (unless force=True).
    Returns {"profile": {...}, "videos": [...], "synced_at": int}.
    """
    profile_cache = _read_cache(channel_id, "profile")
    videos_cache = _read_cache(channel_id, "videos")

    needs_sync = force or _is_stale(profile_cache) or _is_stale(videos_cache)

    if not needs_sync:
        return {
            "profile": profile_cache,
            "videos": videos_cache.get("items", []),
            "synced_at": profile_cache.get("_synced_at", 0),
            "from_cache": True,
        }

    access_token = get_valid_token(channel_id)

    profile = get_user_info(access_token)
    videos = get_videos_with_stats(access_token, limit=50)

    _write_cache(channel_id, "profile", dict(profile))
    _write_cache(channel_id, "videos", {"items": videos})

    return {
        "profile": profile,
        "videos": videos,
        "synced_at": int(time.time()),
        "from_cache": False,
    }


def sync_all_channels(force: bool = False) -> dict[str, dict]:
    """Sync every connected channel. Returns {channel_id: data}."""
    results: dict[str, dict] = {}
    for channel_id in list_connected_channels():
        try:
            results[channel_id] = sync_channel(channel_id, force=force)
        except Exception as exc:
            results[channel_id] = {"error": str(exc)}
    return results


# ── Load ───────────────────────────────────────────────────────────────────────

def load_channel_data(channel_id: str) -> dict | None:
    """Load cached data without hitting API. Returns None if no cache."""
    profile = _read_cache(channel_id, "profile")
    videos = _read_cache(channel_id, "videos")
    if profile is None:
        return None
    return {
        "profile": profile,
        "videos": (videos or {}).get("items", []),
        "synced_at": profile.get("_synced_at", 0),
        "from_cache": True,
    }


# ── Channel list with metadata ─────────────────────────────────────────────────

def get_channel_summary_list() -> list[dict]:
    """
    Return summary list of all connected channels (for sidebar).
    Each item: {channel_id, display_name, follower_count, video_count, synced_at}
    """
    summaries = []
    for channel_id in list_connected_channels():
        profile_cache = _read_cache(channel_id, "profile")
        # Prefer display_name from profile cache (real TikTok username) over token fallback
        display_name = (
            (profile_cache or {}).get("display_name")
            or get_channel_display_name(channel_id)
        )
        summaries.append({
            "channel_id": channel_id,
            "display_name": display_name,
            "follower_count": (profile_cache or {}).get("follower_count", 0),
            "video_count": (profile_cache or {}).get("video_count", 0),
            "avatar_url": (profile_cache or {}).get("avatar_url", ""),
            "synced_at": (profile_cache or {}).get("_synced_at", 0),
            "cache_stale": _is_stale(profile_cache),
        })
    return summaries


# ── Revenue CSV helper ─────────────────────────────────────────────────────────

REVENUE_CACHE_PATH = Path(__file__).parent.parent / "data" / "revenue_data.json"


def save_revenue_data(channel_id: str, records: list[dict]) -> None:
    """Persist revenue records (from CSV upload) for a channel."""
    existing = {}
    if REVENUE_CACHE_PATH.exists():
        with open(REVENUE_CACHE_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing[channel_id] = {"records": records, "updated_at": int(time.time())}
    with open(REVENUE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def load_revenue_data(channel_id: str) -> list[dict]:
    """Load revenue records for a channel."""
    if not REVENUE_CACHE_PATH.exists():
        return []
    with open(REVENUE_CACHE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(channel_id, {}).get("records", [])
