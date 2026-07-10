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

st.set_page_config(page_title="YouTube Kids Channel Analytics", layout="wide")


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

st.title("YouTube Kids Channel Analytics")
st.caption("Videos uploaded in the last 90 days")

# --- Sidebar: channel picker, built to scale to 100+ channels ---
with st.sidebar:
    st.header("Channels")

    channels = channels.copy()
    channels["category"] = channels["category"].fillna("Uncategorized")
    categories = sorted(channels["category"].unique())

    st.write("**Filter by category**")
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
        default=categories,
        key="category_multiselect",
        label_visibility="collapsed",
    )

    category_matched = channels[channels["category"].isin(category_filter)]
    channel_names = category_matched.sort_values("title")["title"].tolist()

    st.divider()

    st.write("**Search channels**")
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
    col_s.metric("Shorts uploaded", total_shorts)
    col_l.metric("Long-form uploaded", total_longform)

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
            color=alt.Color("content_type:N", title="Content type"),
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
        .mark_bar()
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
        .mark_bar()
        .encode(
            x=alt.X("duration_bucket:N", title="Duration bucket", sort=labels),
            y=alt.Y("avg_views:Q", title="Avg. views"),
            tooltip=["duration_bucket", "videos", "avg_views"],
        )
    )
    st.altair_chart(length_chart, use_container_width=True)
    st.dataframe(
        bucket_summary,
        column_config={
            "duration_bucket": st.column_config.TextColumn("Duration bucket", width="medium"),
            "videos": st.column_config.NumberColumn("Videos", width="small", format="%,d"),
            "avg_views": st.column_config.NumberColumn("Avg. views", width="small", format="%,.0f"),
        },
        hide_index=True,
    )

with tab4:
    st.subheader("Channel summary")
    st.dataframe(
        channels[["title", "category", "subscriber_count", "view_count", "video_count"]],
        column_config={
            "title": st.column_config.TextColumn("Channel", width="large"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "subscriber_count": st.column_config.NumberColumn("Subscribers", width="small", format="%,d"),
            "view_count": st.column_config.NumberColumn("Total views", width="small", format="%,d"),
            "video_count": st.column_config.NumberColumn("Total videos", width="small", format="%,d"),
        },
        hide_index=True,
    )