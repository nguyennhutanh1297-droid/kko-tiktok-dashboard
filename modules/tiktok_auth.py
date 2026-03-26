"""
TikTok OAuth 2.0 PKCE authentication module.
Handles connect, token exchange, refresh, and per-channel token storage.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"

TOKENS_PATH = Path(__file__).parent.parent / "data" / "tiktok_tokens.json"

SCOPES = [
    "user.info.basic",
    "user.info.stats",
    "video.list",
]


# ── PKCE helpers ───────────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(redirect_uri: str, state: str, code_challenge: str) -> str:
    """Construct the TikTok authorization URL."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    params = {
        "client_key": client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"


# ── Token exchange ─────────────────────────────────────────────────────────────

def exchange_code_for_token(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange auth code + PKCE verifier for access/refresh tokens."""
    payload = {
        "client_key": os.getenv("TIKTOK_CLIENT_KEY", ""),
        "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    resp = requests.post(TIKTOK_TOKEN_URL, data=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(f"Token exchange error: {data.get('error_description', data['error'])}")
    return data


def refresh_access_token(refresh_token: str) -> dict:
    """Use refresh_token to get a new access_token."""
    payload = {
        "client_key": os.getenv("TIKTOK_CLIENT_KEY", ""),
        "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    resp = requests.post(TIKTOK_TOKEN_URL, data=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(f"Token refresh error: {data.get('error_description', data['error'])}")
    return data


# ── Token storage ──────────────────────────────────────────────────────────────

def _load_tokens() -> dict:
    if TOKENS_PATH.exists():
        with open(TOKENS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_tokens(tokens: dict) -> None:
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2, ensure_ascii=False)


def save_channel_token(channel_id: str, token_data: dict) -> None:
    """Persist token data for a channel, adding expires_at timestamp."""
    tokens = _load_tokens()
    token_data["expires_at"] = int(time.time()) + token_data.get("expires_in", 86400)
    token_data["refresh_expires_at"] = int(time.time()) + token_data.get(
        "refresh_expires_in", 86400 * 30
    )
    tokens[channel_id] = token_data
    _save_tokens(tokens)


def remove_channel_token(channel_id: str) -> None:
    """Disconnect (remove) a channel's tokens."""
    tokens = _load_tokens()
    tokens.pop(channel_id, None)
    _save_tokens(tokens)


def list_connected_channels() -> list[str]:
    """Return list of channel_ids that have stored tokens."""
    return list(_load_tokens().keys())


# ── Main helper ────────────────────────────────────────────────────────────────

def get_valid_token(channel_id: str) -> str:
    """
    Return a valid access_token for the channel.
    Auto-refreshes if expired. Raises if channel not connected.
    """
    tokens = _load_tokens()
    if channel_id not in tokens:
        raise KeyError(f"Channel '{channel_id}' not connected. Please authenticate first.")

    entry = tokens[channel_id]
    now = int(time.time())

    # Access token still valid (60s buffer)
    if entry.get("expires_at", 0) > now + 60:
        return entry["access_token"]

    # Refresh token still valid
    if entry.get("refresh_expires_at", 0) > now:
        new_data = refresh_access_token(entry["refresh_token"])
        new_data["refresh_token"] = entry["refresh_token"]  # keep existing refresh token
        save_channel_token(channel_id, new_data)
        return new_data["access_token"]

    raise ValueError(
        f"Channel '{channel_id}' tokens expired. Please reconnect."
    )


def get_channel_display_name(channel_id: str) -> str:
    """Return display_name stored at token-save time, fallback to channel_id."""
    tokens = _load_tokens()
    entry = tokens.get(channel_id, {})
    return entry.get("display_name") or channel_id
