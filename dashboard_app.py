"""
TikTok Channel Performance Dashboard — main Streamlit entry point.
Run: streamlit run dashboard/dashboard_app.py
"""

import os
import secrets

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
from modules.dashboard_renderer import render_channel_dashboard, render_channel_sidebar

# ── OAuth callback redirect URI ────────────────────────────────────────────────
# When running locally, TikTok redirects back to this URL with ?code=&state=
REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8501")


# ── Session state helpers ──────────────────────────────────────────────────────

def _init_session() -> None:
    if "pkce_verifier" not in st.session_state:
        st.session_state["pkce_verifier"] = None
    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = None


# ── OAuth callback handler ─────────────────────────────────────────────────────

def _handle_oauth_callback() -> bool:
    """
    Check query params for OAuth callback (?code=...&state=...).
    Returns True if callback was handled (page should stop rendering further).
    """
    params = st.query_params
    code = params.get("code")
    state = params.get("state")

    if not code:
        return False

    expected_state = st.session_state.get("oauth_state")
    if state != expected_state:
        st.error("OAuth state mismatch — có thể là CSRF. Thử lại.")
        st.query_params.clear()
        return True

    verifier = st.session_state.get("pkce_verifier")
    if not verifier:
        st.error("Không tìm thấy PKCE verifier trong session. Thử lại.")
        st.query_params.clear()
        return True

    with st.spinner("Đang lấy access token..."):
        try:
            token_data = exchange_code_for_token(code, verifier, REDIRECT_URI)
        except Exception as exc:
            st.error(f"Lỗi lấy token: {exc}")
            st.query_params.clear()
            return True

    # Use open_id as channel_id; store display_name if returned
    channel_id = token_data.get("open_id", token_data.get("user", {}).get("open_id", "unknown"))
    token_data["display_name"] = token_data.get("display_name", channel_id)
    save_channel_token(channel_id, token_data)

    # Clean up session + query params
    st.session_state["pkce_verifier"] = None
    st.session_state["oauth_state"] = None
    st.query_params.clear()

    st.success(f"✅ Đã kết nối kênh: {token_data['display_name']}")
    st.rerun()
    return True


# ── Connect channel UI ─────────────────────────────────────────────────────────

def _render_connect_channel_button() -> None:
    """Button that starts OAuth flow."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    if not client_key:
        st.sidebar.error("Chưa cấu hình TIKTOK_CLIENT_KEY trong .env")
        return

    if st.sidebar.button("➕ Kết nối kênh mới"):
        verifier, challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(16)
        st.session_state["pkce_verifier"] = verifier
        st.session_state["oauth_state"] = state

        auth_url = build_auth_url(REDIRECT_URI, state, challenge)
        # Open in new tab via JS redirect
        st.markdown(
            f'<meta http-equiv="refresh" content="0; url={auth_url}">',
            unsafe_allow_html=True,
        )
        st.info("Đang chuyển hướng đến TikTok để xác thực...")
        st.stop()


def _render_disconnect_button(channel_id: str) -> None:
    """Disconnect (remove) a channel's token."""
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
    _init_session()

    # Handle OAuth redirect callback first
    if _handle_oauth_callback():
        return

    # Sidebar: channel list + connect button
    selected_channel_id = render_channel_sidebar()
    _render_connect_channel_button()

    if selected_channel_id:
        _render_disconnect_button(selected_channel_id)
        st.sidebar.markdown("---")
        st.sidebar.caption("TikTok API v2 · Cache 1h")

    # Main area
    if not list_connected_channels():
        _render_empty_state()
        return

    if selected_channel_id:
        render_channel_dashboard(selected_channel_id)


if __name__ == "__main__":
    main()
