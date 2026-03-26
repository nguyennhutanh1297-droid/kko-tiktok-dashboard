"""
TikTok Channel Performance Dashboard — main Streamlit entry point.
Run: streamlit run dashboard/dashboard_app.py
"""

import json
import os
import secrets
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Must be first Streamlit call
st.set_page_config(
    page_title="TikTok Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from modules.tiktok_auth import (
    build_auth_url,
    exchange_code_for_token,
    generate_pkce_pair,
    list_connected_channels,
    remove_channel_token,
    save_channel_token,
)
from modules.dashboard_renderer import (
    render_channel_dashboard,
    render_channel_sidebar,
    render_overview_dashboard,
    OVERVIEW_KEY,
)

REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8502")

# Temp file to persist PKCE verifier across sessions/tabs
_PKCE_STORE = Path(__file__).parent / "data" / "pkce_pending.json"


# ── PKCE persistence (file-based, survives new tab = new session) ──────────────

def _save_pkce(state: str, verifier: str) -> None:
    _PKCE_STORE.parent.mkdir(parents=True, exist_ok=True)
    store = {}
    if _PKCE_STORE.exists():
        store = json.loads(_PKCE_STORE.read_text())
    # Prune entries older than 10 minutes
    now = time.time()
    store = {k: v for k, v in store.items() if now - v.get("ts", 0) < 600}
    store[state] = {"verifier": verifier, "ts": now}
    _PKCE_STORE.write_text(json.dumps(store))


def _pop_pkce(state: str) -> str | None:
    if not _PKCE_STORE.exists():
        return None
    store = json.loads(_PKCE_STORE.read_text())
    entry = store.pop(state, None)
    _PKCE_STORE.write_text(json.dumps(store))
    return entry["verifier"] if entry else None


# ── OAuth callback handler ─────────────────────────────────────────────────────

def _handle_oauth_callback() -> bool:
    """Check query params for ?code=&state= OAuth callback."""
    params = st.query_params
    code = params.get("code")
    state = params.get("state")

    if not code:
        return False

    verifier = _pop_pkce(state)
    if not verifier:
        st.error("Session hết hạn hoặc state không hợp lệ. Vui lòng thử lại.")
        st.query_params.clear()
        return True

    with st.spinner("Đang lấy access token..."):
        try:
            token_data = exchange_code_for_token(code, verifier, REDIRECT_URI)
        except Exception as exc:
            st.error(f"Lỗi lấy token: {exc}")
            st.query_params.clear()
            return True

    channel_id = token_data.get("open_id", "unknown")
    token_data["display_name"] = token_data.get("display_name", channel_id)
    save_channel_token(channel_id, token_data)
    st.query_params.clear()

    st.success(f"✅ Đã kết nối kênh: {token_data['display_name']}")
    st.rerun()
    return True


# ── Connect channel UI ─────────────────────────────────────────────────────────

def _render_connect_channel_button() -> None:
    """Button that starts OAuth flow via link_button (opens new tab)."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    if not client_key:
        st.sidebar.error("Chưa cấu hình TIKTOK_CLIENT_KEY")
        return

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    _save_pkce(state, verifier)
    auth_url = build_auth_url(REDIRECT_URI, state, challenge)

    st.sidebar.link_button("➕ Kết nối kênh mới", auth_url, use_container_width=True)
    st.sidebar.caption("Mở TikTok → Authorize → quay về tab này")


def _render_disconnect_button(channel_id: str) -> None:
    if st.sidebar.button("🔌 Ngắt kết nối kênh này", key=f"disc_{channel_id}"):
        remove_channel_token(channel_id)
        st.rerun()


# ── No channels state ──────────────────────────────────────────────────────────

def _render_empty_state() -> None:
    st.markdown(
        """
        <div style='text-align:center; padding:4rem 2rem;'>
            <h1>📊 TikTok Performance Dashboard</h1>
            <p style='font-size:1.2rem; color:#888;'>
                Kết nối kênh TikTok của bạn để bắt đầu theo dõi performance.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Handle OAuth redirect callback first
    if _handle_oauth_callback():
        return

    # Sidebar
    selected_channel_id = render_channel_sidebar()
    _render_connect_channel_button()

    if selected_channel_id and selected_channel_id != OVERVIEW_KEY:
        _render_disconnect_button(selected_channel_id)
        st.sidebar.markdown("---")
        st.sidebar.caption("TikTok API v2 · Cache 1h")

    # Main area
    if not list_connected_channels():
        _render_empty_state()
        return

    if selected_channel_id == OVERVIEW_KEY:
        render_overview_dashboard()
    elif selected_channel_id:
        render_channel_dashboard(selected_channel_id)


if __name__ == "__main__":
    main()
