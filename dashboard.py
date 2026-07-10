"""
dashboard.py

Reads from youtube_data.db (created by fetch_data.py) and renders a general
YouTube channel/video performance dashboard: upload trends, top content,
content-length breakdown, and a channel summary.

Run with:
    streamlit run dashboard.py
"""

import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = "youtube_data.db"

st.set_page_config(page_title="YouTube Kids Channel Analytics", page_icon="🎬", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap');

    .block-container {
        padding-top: 1.5rem;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    h1 {
        font-family: 'Baloo 2', sans-serif !important;
        color: #22223B !important;
    }

    h2, h3 {
        font-family: 'Baloo 2', sans-serif !important;
        color: #6A4C93 !important;
    }

    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace;
        color: #FF6B6B;
    }

    [data-testid="stMetric"] {
        background-color: #F3EFE3;
        border-radius: 12px;
        border-top: 4px solid #2EC4B6;
        padding: 12px 16px 8px 16px;
    }

    .stTabs [aria-selected="true"] {
        color: #FF6B6B !important;
        border-bottom-color: #FF6B6B !important;
    }

    section[data-testid="stSidebar"] {
        background-color: #F3EFE3;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="display: flex; align-items: center; gap: 14px; margin-bottom: -8px;">
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="24" width="8" height="18" rx="2" fill="#FF6B6B"/>
            <rect x="14" y="14" width="8" height="28" rx="2" fill="#2EC4B6"/>
            <rect x="26" y="6" width="8" height="36" rx="2" fill="#FFC145"/>
            <circle cx="38" cy="10" r="6" fill="#6A4C93"/>
            <path d="M36 7.5L41 10L36 12.5V7.5Z" fill="#FFFDF7"/>
        </svg>
        <h1 style="margin: 0;">YouTube Kids Channel Analytics</h1>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("Videos uploaded in the last 90 days")


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    channels = pd.read_sql("SELECT * FROM channels", conn)
    videos = pd.read_sql("SELECT * FROM videos", conn)
    conn.close()

    videos["published_at"] = pd.to_datetime(videos["published_at"])
    videos["content_type"] = videos["is_short"].map({1: "Short", 0: "Long-form"})
    videos["publish_month"] = videos["published_at"].dt.to_period("M").astype(str)

    return channels, videos


channels, videos = load_data()

# --- Sidebar: channel picker, built to scale to 100+ channels ---
with st.sidebar:
    st.header("Channels")

    channels = channels.copy()
    channels["category"] = channels["category"].fillna("Uncategorized").str.title()
    categories = sorted(channels["category"].unique())

    st.write("**Filter by category**")
    st.caption("Leave empty to show all categories")
    cat_col_a, cat_col_b = st.columns(2)
    if cat_col_a.button("Select all categories", use_container_width=True):
        st.session_state.category_multiselect = categories
    if cat_col_b.button("Clear categories", use_container_width=True):
        st.session_state.category_multiselect = []

    if "category_multiselect" in st.session_state:
        st.session_state.category_multiselect = [
            c for c in st.session_state.category_multiselect if c in categories
        ]

    category_filter = st.multiselect(
        "Filter by category",
        categories,
        default=[],
        key="category_multiselect",
        label_visibility="collapsed",
    )

    # An empty selection means "no category restriction" (show everything),
    # not "show nothing" -- categories only narrow things down when chosen.
    if category_filter:
        category_matched = channels[channels["category"].isin(category_filter)]
    else:
        category_matched = channels

    st.divider()

    st.write("**Search channels**")
    search_query = st.text_input(
        "Search channels by name",
        "",
        label_visibility="collapsed",
        placeholder="Search by name...",
    )
    if search_query:
        name_matched = category_matched[
            category_matched["title"].str.contains(search_query, case=False, na=False)
        ]
    else:
        name_matched = category_matched

    channel_names = name_matched.sort_values("title")["title"].tolist()

    chan_col_a, chan_col_b = st.columns(2)
    if chan_col_a.button("Select all channels", use_container_width=True):
        st.session_state.channel_multiselect = channel_names
    if chan_col_b.button("Clear channels", use_container_width=True):
        st.session_state.channel_multiselect = []

    if "channel_multiselect" in st.session_state:
        st.session_state.channel_multiselect = [
            c for c in st.session_state.channel_multiselect if c in channel_names
        ]

    selected = st.multiselect(
        "Search channels",
        channel_names,
        default=channel_names,
        key="channel_multiselect",
        label_visibility="collapsed",
    )

    st.caption(f"{len(selected)} of {len(channel_names)} channels selected")

filtered = videos.merge(
    channels[["channel_id", "title"]].rename(columns={"title": "channel_title"}),
    on="channel_id",
)
filtered = filtered[filtered["channel_title"].isin(selected)]

# --- Top-line metrics ---
col1, col2, col3 = st.columns(3)
col1.metric("Total videos", f"{len(filtered):,}")
col2.metric("Total views", f"{filtered['view_count'].sum():,}")
col3.metric("Avg. views/video", f"{filtered['view_count'].mean():,.0f}" if len(filtered) else "0")

tab1, tab2, tab3, tab4 = st.tabs(
    ["Upload activity", "Top content", "Content length", "Channel summary"]
)

with tab1:
    st.subheader("Uploads by content type")
    total_shorts = int((filtered["content_type"] == "Short").sum())
    total_longform = int((filtered["content_type"] == "Long-form").sum())
    col_s, col_l = st.columns(2)
    col_s.metric("Shorts uploaded", f"{total_shorts:,}")
    col_l.metric("Long-form uploaded", f"{total_longform:,}")

    st.subheader("Uploads over time, by type")
    monthly_by_type = (
        filtered.groupby(["publish_month", "content_type"])
        .size()
        .reset_index(name="videos")
    )
    upload_chart = (
        alt.Chart(monthly_by_type)
        .mark_bar()
        .encode(
            x=alt.X("publish_month:N", title="Month"),
            y=alt.Y("videos:Q", title="Videos"),
            color=alt.Color(
                "content_type:N",
                title="Content type",
                scale=alt.Scale(domain=["Short", "Long-form"], range=["#FF6B6B", "#2EC4B6"]),
            ),
            tooltip=["publish_month", "content_type", "videos"],
        )
    )
    st.altair_chart(upload_chart, use_container_width=True)

    st.subheader("Total views over time")
    filter_view_outliers = st.checkbox(
        "Filter out top 1% view outliers (a single viral/compilation video can flatten this chart)",
        value=True,
    )
    views_df = filtered.copy()
    if filter_view_outliers and len(views_df) > 0:
        cutoff = views_df["view_count"].quantile(0.99)
        views_df = views_df[views_df["view_count"] <= cutoff]
    monthly_views = (
        views_df.groupby("publish_month")["view_count"]
        .sum()
        .reset_index()
        .sort_values("publish_month")
    )
    views_chart = (
        alt.Chart(monthly_views)
        .mark_bar(color="#6A4C93")
        .encode(
            x=alt.X("publish_month:N", title="Month"),
            y=alt.Y("view_count:Q", title="Total views"),
            tooltip=["publish_month", "view_count"],
        )
    )
    st.altair_chart(views_chart, use_container_width=True)

    st.subheader("Upload mix by channel")
    mix_by_channel = (
        filtered.groupby(["channel_title", "content_type"])
        .size()
        .reset_index(name="videos")
        .pivot(index="channel_title", columns="content_type", values="videos")
        .fillna(0)
        .reset_index()
    )
    st.dataframe(
        mix_by_channel,
        column_config={
            "channel_title": st.column_config.TextColumn("Channel", width="large"),
            "Short": st.column_config.NumberColumn(width="small", format="%,d"),
            "Long-form": st.column_config.NumberColumn(width="small", format="%,d"),
        },
        hide_index=True,
    )

with tab2:
    st.subheader("Top 50 videos by views")
    top = filtered.sort_values("view_count", ascending=False).head(50).copy()
    top["url"] = "https://www.youtube.com/watch?v=" + top["video_id"]
    st.dataframe(
        top[["title", "channel_title", "video_id", "url", "content_type", "view_count"]],
        column_config={
            "title": st.column_config.TextColumn("Title", width="large"),
            "channel_title": st.column_config.TextColumn("Channel", width="medium"),
            "video_id": st.column_config.TextColumn("Video ID", width="small"),
            "url": st.column_config.LinkColumn("Watch", display_text="Open ↗", width="small"),
            "content_type": st.column_config.TextColumn("Type", width="small"),
            "view_count": st.column_config.NumberColumn("Views", width="small", format="%,d"),
        },
        hide_index=True,
    )

with tab3:
    st.subheader("Views by content length")
    bins = [0, 60, 300, 600, 1200, 1800, 3600, 999999]
    labels = ["<1min (Short)", "1-5min", "5-10min", "10-20min", "20-30min", "30-60min", "60min+"]
    plot_df = filtered.copy()
    plot_df["duration_bucket"] = pd.cut(
        plot_df["duration_seconds"], bins=bins, labels=labels, right=True
    )
    bucket_summary = (
        plot_df.groupby("duration_bucket", observed=True)
        .agg(videos=("video_id", "count"), avg_views=("view_count", "mean"))
        .reset_index()
    )
    length_chart = (
        alt.Chart(bucket_summary)
        .mark_bar(color="#FFC145")
        .encode(
            x=alt.X("duration_bucket:N", title="Duration bucket", sort=labels),
            y=alt.Y("avg_views:Q", title="Avg. views"),
            tooltip=["duration_bucket", "videos", "avg_views"],
        )
    )
    st.altair_chart(length_chart, use_container_width=True)

    bucket_summary_sorted = bucket_summary.sort_values("avg_views", ascending=False)
    st.dataframe(
        bucket_summary_sorted,
        column_config={
            "duration_bucket": st.column_config.TextColumn("Duration bucket", width="medium"),
            "videos": st.column_config.NumberColumn("Videos", width="small", format="%,d"),
            "avg_views": st.column_config.NumberColumn("Avg. views", width="small", format="%,.0f"),
        },
        hide_index=True,
    )

with tab4:
    st.subheader("Channel summary")
    channel_summary_sorted = channels[
        ["title", "category", "subscriber_count", "view_count", "video_count"]
    ].sort_values("view_count", ascending=False)
    st.dataframe(
        channel_summary_sorted,
        column_config={
            "title": st.column_config.TextColumn("Channel", width="large"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "subscriber_count": st.column_config.NumberColumn("Subscribers", width="small", format="%,d"),
            "view_count": st.column_config.NumberColumn("Total views", width="small", format="%,d"),
            "video_count": st.column_config.NumberColumn("Total videos", width="small", format="%,d"),
        },
        hide_index=True,
    )
