"""
Streamlit UI components for the TikTok Channel Performance Dashboard.
Each render_* function writes directly to Streamlit context.
"""

from __future__ import annotations

import io
import time
from datetime import datetime, timedelta, date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .tiktok_data_sync import (
    get_channel_summary_list,
    load_channel_data,
    load_revenue_data,
    save_revenue_data,
    sync_channel,
)
from .tiktok_auth import list_connected_channels


# ── Formatters ─────────────────────────────────────────────────────────────────

def _fmt_number(n: int | float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _fmt_time(ts: int) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


# ── KPI cards ──────────────────────────────────────────────────────────────────

def render_kpi_cards(profile: dict, videos: list[dict], revenue_total: float) -> None:
    """4 top-level metric cards."""
    followers = profile.get("follower_count", 0)
    total_views = sum(v.get("view_count") or v.get("play_count") or 0 for v in videos)
    avg_er = (
        round(sum(v.get("engagement_rate", 0) for v in videos) / len(videos), 2)
        if videos
        else 0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Followers", _fmt_number(followers))
    c2.metric("▶️ Tổng Views", _fmt_number(total_views))
    c3.metric("💬 Avg ER%", f"{avg_er}%")
    c4.metric("💰 Revenue", f"${revenue_total:,.0f}" if revenue_total else "N/A")


# ── Charts ─────────────────────────────────────────────────────────────────────

def render_views_bar_chart(videos: list[dict], top_n: int = 10) -> None:
    """Bar chart: Top N videos by views."""
    if not videos:
        st.info("Chưa có dữ liệu video.")
        return

    df = pd.DataFrame(videos).head(top_n)
    df["views"] = df.get("view_count", df.get("play_count", pd.Series([0] * len(df))))
    df["label"] = df["title"].str[:40] + "…"

    fig = px.bar(
        df,
        x="views",
        y="label",
        orientation="h",
        title=f"Top {top_n} Videos theo Views",
        labels={"views": "Lượt xem", "label": ""},
        color="views",
        color_continuous_scale="Blues",
    )
    fig.update_layout(height=350, showlegend=False, coloraxis_showscale=False)
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)


def render_engagement_chart(videos: list[dict]) -> None:
    """Horizontal bar: avg likes / comments / shares per video."""
    if not videos:
        return

    avg_likes = sum(v.get("like_count", 0) for v in videos) / len(videos)
    avg_comments = sum(v.get("comment_count", 0) for v in videos) / len(videos)
    avg_shares = sum(v.get("share_count", 0) for v in videos) / len(videos)

    fig = go.Figure(go.Bar(
        x=[avg_likes, avg_comments, avg_shares],
        y=["Likes", "Comments", "Shares"],
        orientation="h",
        marker_color=["#FF4444", "#4444FF", "#44BB44"],
    ))
    fig.update_layout(
        title="Avg Engagement per Video",
        height=220,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_er_trend_chart(videos: list[dict]) -> None:
    """Line chart: engagement rate over last 20 videos (chronological)."""
    if len(videos) < 2:
        return

    chronological = sorted(videos, key=lambda v: v.get("create_time", 0))[-20:]
    df = pd.DataFrame(chronological)
    df["date"] = pd.to_datetime(df["create_time"], unit="s", errors="coerce")
    df["er"] = df.get("engagement_rate", pd.Series([0.0] * len(df)))

    fig = px.line(
        df,
        x="date",
        y="er",
        title="Engagement Rate (20 video gần nhất)",
        labels={"date": "", "er": "ER%"},
        markers=True,
    )
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)


# ── Video Table ────────────────────────────────────────────────────────────────

def render_video_table(videos: list[dict]) -> None:
    """Sortable dataframe of all videos with key stats."""
    if not videos:
        st.info("Không có video nào trong cache.")
        return

    rows = []
    for v in videos:
        views = v.get("view_count") or v.get("play_count") or 0
        rows.append({
            "Tiêu đề": (v.get("title") or "—")[:60],
            "Ngày đăng": _fmt_time(v.get("create_time", 0)),
            "Views": views,
            "Likes": v.get("like_count", 0),
            "Comments": v.get("comment_count", 0),
            "Shares": v.get("share_count", 0),
            "ER%": v.get("engagement_rate", 0),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Views": st.column_config.NumberColumn(format="%d"),
            "ER%": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )


# ── Revenue Section ────────────────────────────────────────────────────────────

def render_revenue_section(channel_id: str) -> float:
    """
    Revenue section: show stored data + CSV upload.
    Returns total revenue (float) to display in KPI card.
    """
    records = load_revenue_data(channel_id)
    total = 0.0

    if records:
        df = pd.DataFrame(records)
        numeric_cols = df.select_dtypes("number").columns.tolist()
        if numeric_cols:
            total = df[numeric_cols[0]].sum()

        st.subheader("💰 Revenue / Affiliate")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"Tổng: **${total:,.2f}**")
    else:
        st.info("Chưa có dữ liệu doanh thu. Upload CSV từ TikTok Studio.")

    with st.expander("📤 Upload Revenue CSV"):
        uploaded = st.file_uploader(
            "CSV export từ TikTok Studio / TikTok Shop",
            type=["csv"],
            key=f"revenue_csv_{channel_id}",
        )
        if uploaded is not None:
            try:
                df_up = pd.read_csv(io.StringIO(uploaded.read().decode("utf-8")))
                save_revenue_data(channel_id, df_up.to_dict(orient="records"))
                st.success(f"Đã lưu {len(df_up)} dòng dữ liệu revenue.")
                st.rerun()
            except Exception as exc:
                st.error(f"Lỗi đọc CSV: {exc}")

    return total


# ── Channel sidebar ────────────────────────────────────────────────────────────

def render_channel_sidebar() -> str | None:
    """
    Render sidebar with list of connected channels.
    Returns the selected channel_id (or None if none connected).
    """
    st.sidebar.title("📊 TikTok Dashboard")
    summaries = get_channel_summary_list()

    if not summaries:
        st.sidebar.warning("Chưa kết nối kênh nào.")
        return None

    options = {s["display_name"]: s["channel_id"] for s in summaries}
    selected_name = st.sidebar.radio(
        "Chọn kênh",
        list(options.keys()),
        format_func=lambda n: n,
    )
    selected_id = options[selected_name]

    # Show mini stats for selected channel in sidebar
    sel = next(s for s in summaries if s["channel_id"] == selected_id)
    st.sidebar.markdown("---")
    st.sidebar.metric("Followers", _fmt_number(sel["follower_count"]))
    st.sidebar.metric("Videos", sel["video_count"])
    if sel["synced_at"]:
        st.sidebar.caption(f"Sync: {_fmt_time(sel['synced_at'])}")
    if sel["cache_stale"]:
        st.sidebar.warning("Cache cũ hơn 1 giờ")

    return selected_id


# ── Main channel view ──────────────────────────────────────────────────────────

def render_channel_dashboard(channel_id: str) -> None:
    """Full dashboard view for a single channel."""
    # Sync controls
    col_title, col_sync = st.columns([5, 1])
    with col_title:
        data = load_channel_data(channel_id)
        name = (data or {}).get("profile", {}).get("display_name", channel_id)
        st.title(f"@{name}")
    with col_sync:
        st.write("")
        if st.button("🔄 Sync", key=f"sync_{channel_id}"):
            with st.spinner("Đang sync dữ liệu..."):
                try:
                    data = sync_channel(channel_id, force=True)
                    st.success("Sync xong!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Sync lỗi: {exc}")
                    return

    # Load data (from cache or fresh sync)
    if data is None:
        with st.spinner("Đang tải dữ liệu lần đầu..."):
            try:
                data = sync_channel(channel_id, force=False)
            except Exception as exc:
                st.error(f"Không lấy được dữ liệu: {exc}")
                return

    profile = data.get("profile", {})
    all_videos = data.get("videos", [])

    # ── Time range filter ──────────────────────────────────────────────────────
    today = date.today()
    default_start = today - timedelta(days=30)
    date_range = st.date_input(
        "📅 Khoảng thời gian",
        value=(default_start, today),
        max_value=today,
        key=f"daterange_{channel_id}",
    )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_ts = int(datetime.combine(date_range[0], datetime.min.time()).timestamp())
        end_ts = int(datetime.combine(date_range[1], datetime.max.time()).timestamp())
        videos = [v for v in all_videos if start_ts <= (v.get("create_time") or 0) <= end_ts]
    else:
        videos = all_videos

    if not videos and all_videos:
        st.info("Không có video trong khoảng thời gian này.")

    # Revenue (load first to pass total into KPI)
    revenue_total = sum(
        r.get("amount", r.get("revenue", r.get("gmv", 0)) or 0)
        for r in load_revenue_data(channel_id)
    )

    # KPI cards
    render_kpi_cards(profile, videos, revenue_total)

    st.markdown("---")

    # Charts — two columns
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        render_views_bar_chart(videos)
    with chart_col2:
        render_engagement_chart(videos)
        render_er_trend_chart(videos)

    st.markdown("---")

    # Video table
    st.subheader("🎬 Videos")
    render_video_table(videos)

    st.markdown("---")

    # Revenue
    render_revenue_section(channel_id)
