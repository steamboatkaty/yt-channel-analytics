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
import os

DB_PATH = "youtube_data.db"

DRIVE_FILE_ID = "1b49mjX35FMz-G4SHQXd7ew3Yb3sWbev6"


def ensure_db_exists():
    """
    Locally, youtube_data.db already exists on disk. On Streamlit Cloud,
    it's not in the git repo (gitignored for local dev, and too large/
    dynamic to want in version control) -- so on a fresh deploy it won't
    exist yet. Download it from Google Drive once, only if it's missing.
    """
    if not os.path.exists(DB_PATH):
        import gdown
        with st.spinner("Downloading database (first run only)..."):
            gdown.download(id=DRIVE_FILE_ID, output=DB_PATH, quiet=False)


ensure_db_exists()

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
    themes = pd.read_sql("SELECT * FROM video_themes", conn)
    conn.close()

    videos["published_at"] = pd.to_datetime(videos["published_at"])
    videos["actual_start_time"] = pd.to_datetime(videos["actual_start_time"], errors="coerce")
    videos["actual_end_time"] = pd.to_datetime(videos["actual_end_time"], errors="coerce")

    # A video counts as a Livestream if YouTube's own liveStreamingDetails
    # says so (it has an actual start time) -- this is ground truth, unlike
    # the title regex, which stays only as a fallback for older rows fetched
    # before this field was collected.
    is_livestream = videos["actual_start_time"].notna() | videos["title"].str.contains(
        r"🔴|\blive\b", regex=True, na=False, case=False
    )
    videos["content_type"] = videos["is_short"].map({1: "Short", 0: "Long-form"})
    videos.loc[is_livestream, "content_type"] = "Livestream"
    videos["publish_month"] = videos["published_at"].dt.to_period("M").astype(str)
    videos["publish_week"] = videos["published_at"].dt.to_period("W").dt.start_time

    # Real stream duration where YouTube gave us both endpoints; NaN
    # everywhere else (Shorts, long-form, or streams still missing data).
    videos["stream_duration_seconds"] = (
            videos["actual_end_time"] - videos["actual_start_time"]
    ).dt.total_seconds()

    # Views per day since published -- raw view_count unfairly favors
    # older uploads within the 90-day window just because they've had
    # more time to accumulate views. Clipped to a 1-day minimum so a
    # video published a few hours ago doesn't produce a wildly inflated
    # number from dividing by a tiny fraction of a day.
    days_since_published = (
        pd.Timestamp.now(tz="UTC") - videos["published_at"]
    ).dt.total_seconds() / 86400
    videos["views_per_day"] = videos["view_count"] / days_since_published.clip(lower=1)

    return channels, videos, themes


channels, videos, themes = load_data()

def get_theme_data(filtered_videos: pd.DataFrame, themes: pd.DataFrame, method: str) -> pd.DataFrame:
    """Join filtered videos with their theme label for a specific method."""
    method_themes = themes[themes["method"] == method]
    return filtered_videos.merge(method_themes[["video_id", "theme_label"]], on="video_id", how="inner")

# --- Sidebar: channel picker, built to scale to 100+ channels ---
with st.sidebar:
    st.header("Channels")

    channels = channels.copy()
    channels["category"] = channels["category"].fillna("Uncategorized").str.title()
    categories = sorted(channels["category"].unique())

    st.session_state.setdefault("category_multiselect", [])
    st.session_state.category_multiselect = [
        c for c in st.session_state.category_multiselect if c in categories
    ]

    st.write("**Filter by category**")
    st.caption("Leave empty to show all categories")
    cat_col_a, cat_col_b = st.columns(2)
    if cat_col_a.button("Select all categories", width="stretch"):
        st.session_state.category_multiselect = categories
    if cat_col_b.button("Clear categories", width="stretch"):
        st.session_state.category_multiselect = []

    category_filter = st.multiselect(
        "Filter by category",
        categories,
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
    channel_names = category_matched.sort_values("title")["title"].tolist()

    st.session_state.setdefault("channel_multiselect", [])
    st.session_state.channel_multiselect = [
        c for c in st.session_state.channel_multiselect if c in channel_names
    ]

    chan_col_a, chan_col_b = st.columns(2)
    if chan_col_a.button("Select all channels", width="stretch"):
        st.session_state.channel_multiselect = channel_names
    if chan_col_b.button("Clear channels", width="stretch"):
        st.session_state.channel_multiselect = []

    selected = st.multiselect(
        "Search channels",
        channel_names,
        key="channel_multiselect",
        label_visibility="collapsed",
        placeholder="Type to search channels...",
    )

    if selected:
        st.caption(f"{len(selected)} of {len(channel_names)} channels selected")
    else:
        st.caption(f"Showing all {len(channel_names)} channels")

filtered = videos.merge(
    channels[["channel_id", "title"]].rename(columns={"title": "channel_title"}),
    on="channel_id",
)
# If specific channels are picked, use exactly those. Otherwise fall back to
# whatever the category filter already narrowed things down to (which is
# itself "everything" if no category is selected either).
effective_channels = selected if selected else channel_names
filtered = filtered[filtered["channel_title"].isin(effective_channels)]

# --- Top-line metrics ---
col1, col2, col3 = st.columns(3)
col1.metric("Total videos", f"{len(filtered):,}")
col2.metric("Total views", f"{filtered['view_count'].sum():,}")
col3.metric("Avg. views/video", f"{filtered['view_count'].mean():,.0f}" if len(filtered) else "0")

tab1, tab2, tab3, tab6, tab4 = st.tabs(
    ["Upload activity", "Top content", "Content length", "Livestreams", "Channels Overview"]
)

with tab1:
    st.subheader("Uploads by content type")
    total_shorts = int((filtered["content_type"] == "Short").sum())
    total_longform = int((filtered["content_type"] == "Long-form").sum())
    total_livestream = int((filtered["content_type"] == "Livestream").sum())
    col_s, col_l, col_ls = st.columns(3)
    col_s.metric("Shorts uploaded", f"{total_shorts:,}")
    col_l.metric("Long-form uploaded", f"{total_longform:,}")
    col_ls.metric("Livestreams uploaded", f"{total_livestream:,}")

    livestream_durations = filtered.loc[
        filtered["content_type"] == "Livestream", "stream_duration_seconds"
    ].dropna()
    if not livestream_durations.empty:
        avg_minutes = livestream_durations.mean() / 60
        st.caption(
            f"Avg. livestream duration (from YouTube's actual start/end times, "
            f"available for {len(livestream_durations):,} of {total_livestream:,} "
            f"livestream(s)): **{avg_minutes:,.0f} min**"
        )

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
                scale=alt.Scale(
                    domain=["Short", "Long-form", "Livestream"],
                    range=["#FF6B6B", "#2EC4B6", "#FFC145"],
                ),
            ),
            tooltip=["publish_month", "content_type", "videos"],
        )
    )
    st.altair_chart(upload_chart, width="stretch")

    st.subheader("Total views over time, by type")
    views_by_type = (
        filtered.groupby(["publish_month", "content_type"])["view_count"]
        .sum()
        .reset_index()
    )
    views_by_type_chart = (
        alt.Chart(views_by_type)
        .mark_bar()
        .encode(
            x=alt.X("publish_month:N", title="Month"),
            y=alt.Y("view_count:Q", title="Total views"),
            color=alt.Color(
                "content_type:N",
                title="Content type",
                scale=alt.Scale(
                    domain=["Short", "Long-form", "Livestream"],
                    range=["#FF6B6B", "#2EC4B6", "#FFC145"],
                )
            ),
            tooltip=["publish_month", "content_type", "view_count"],
        )
    )
    st.altair_chart(views_by_type_chart, width="stretch")

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
        views_df.groupby("publish_week")["view_count"]
        .sum()
        .reset_index()
        .sort_values("publish_week")
    )
    # Drop the most recent week -- it's always incomplete/artificially low
    # since videos published a few days ago haven't had time to accumulate
    # views yet, and the week itself may not even be over.
    if len(monthly_views) > 1:
        monthly_views = monthly_views.iloc[:-1]

    y_max = monthly_views["view_count"].max() * 1.25
    views_chart = (
        alt.Chart(monthly_views)
        .mark_line(color="#6A4C93", point=True)
        .encode(
            x=alt.X("publish_week:T", title="Week", axis=alt.Axis(format="%d %b")),
            y=alt.Y("view_count:Q", title="Total views", scale=alt.Scale(domain=[0, y_max])),
            tooltip=["publish_week", "view_count"],
        )
    )
    st.altair_chart(views_chart, width="stretch")



    st.subheader("Upload mix by channel")
    mix_by_channel = (
        filtered.groupby(["channel_title", "content_type"])
        .size()
        .reset_index(name="videos")
        .pivot(index="channel_title", columns="content_type", values="videos")
        .fillna(0)
        .reindex(columns=["Long-form", "Short", "Livestream"], fill_value=0)
        .reset_index()
        .sort_values("Long-form", ascending=False)
    )
    st.dataframe(
        mix_by_channel[["channel_title", "Long-form", "Short", "Livestream"]],
        column_config={
            "channel_title": st.column_config.TextColumn("Channel", width="medium"),
            "Long-form": st.column_config.NumberColumn(width="small", format="%,d"),
            "Short": st.column_config.NumberColumn(width="small", format="%,d"),
            "Livestream": st.column_config.NumberColumn(width="small", format="%,d"),
        },
        hide_index=True,
    )

with tab2:
    st.subheader("Top 50 videos by views")
    top = filtered.sort_values("view_count", ascending=False).head(50).copy()
    top["url"] = "https://www.youtube.com/watch?v=" + top["video_id"]

    top5 = top.head(5)
    cols = st.columns(5)
    for rank, (col, (_, video)) in enumerate(zip(cols, top5.iterrows()), start=1):
        with col:
            st.image(f"https://img.youtube.com/vi/{video['video_id']}/hqdefault.jpg", width="stretch")
            st.markdown(f"**#{rank}**")
            title = video["title"]
            st.markdown(
                f'<div style="height: 3em; overflow: hidden; display: -webkit-box; '
                f'-webkit-line-clamp: 2; -webkit-box-orient: vertical;">{title}</div>',
                unsafe_allow_html=True,
            )
            st.caption(video["channel_title"])
            st.markdown(f"**{video['view_count']:,}** views")
            st.link_button("Watch ↗", video["url"], width="stretch")
    st.dataframe(
        top[[
            "channel_title", "title", "url", "view_count", "views_per_day", "published_at", "video_id", "content_type"
        ]],
        column_config={
            "channel_title": st.column_config.TextColumn("Channel", width="medium"),
            "title": st.column_config.TextColumn("Title", width="medium"),
            "view_count": st.column_config.NumberColumn("Views", width="small", format="%,d"),
            "published_at": st.column_config.DatetimeColumn("Published", width="small", format="D MMM YYYY"),
            "video_id": st.column_config.TextColumn("Video ID", width="small"),
            "url": st.column_config.LinkColumn("Watch", display_text="Open ↗", width="small"),
            "content_type": st.column_config.TextColumn("Type", width="small"),
    "views_per_day": st.column_config.NumberColumn("Views/day", width="small", format="%,.0f"),
        },
        hide_index=True,
    )

with tab3:
    st.subheader("Views by content length")
    bins = [0, 60, 600, 1800, 3600, 5400, 999999]
    labels = ["Shorts", "1-10 min", "10-30 min", "30-60 min", "60-90 min", "90+ min"]
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
    st.altair_chart(length_chart, width="stretch")

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

with tab6:
    st.subheader("Livestreams")

    livestream_videos = filtered[filtered["content_type"] == "Livestream"].copy()

    if livestream_videos.empty:
        st.info("No livestreams in the current filter selection.")
    else:
        total_streams = len(livestream_videos)
        avg_views = livestream_videos["view_count"].mean()
        total_views_all = livestream_videos["view_count"].sum()
        durations = livestream_videos["stream_duration_seconds"].dropna()

        col_ls1, col_ls2, col_ls3, col_ls4 = st.columns(4)
        col_ls1.metric("Total livestreams", f"{total_streams:,}")
        col_ls2.metric("Avg. views", f"{avg_views:,.0f}")
        col_ls4.metric("Total views", f"{total_views_all:,}")
        if not durations.empty:
            col_ls3.metric(
                "Avg. duration",
                f"{durations.mean() / 60:,.0f} min",
                help=f"Based on {len(durations):,} of {total_streams:,} livestreams with a recorded end time.",
            )
        else:
            col_ls3.metric(
                "Avg. duration", "N/A",
                help="No livestreams in this selection have a recorded end time yet.",
            )
        channel_ls_summary = (
            livestream_videos.groupby("channel_title")
            .agg(
                livestreams=("video_id", "count"),
                avg_views=("view_count", "mean"),
                total_views=("view_count", "sum"),
                avg_duration_seconds=("stream_duration_seconds", "mean"),
                avg_concurrent_viewers=("concurrent_viewers", "mean"),
            )
            .reset_index()
            .sort_values("total_views", ascending=False)
        )

        st.subheader("Summary by channel")
        summary_table = channel_ls_summary.copy()
        summary_table["avg_duration_min"] = summary_table["avg_duration_seconds"] / 60

        st.dataframe(
            summary_table[
                ["channel_title", "livestreams", "avg_views", "total_views", "avg_duration_min"]
            ],
            column_config={
                "channel_title": st.column_config.TextColumn("Channel", width="medium"),
                "livestreams": st.column_config.NumberColumn("Livestreams", width="small", format="%,d"),
                "avg_views": st.column_config.NumberColumn("Avg. views", width="small", format="%,d"),
                "total_views": st.column_config.NumberColumn("Total views", width="small", format="%,d"),
                "avg_duration_min": st.column_config.NumberColumn("Avg. duration (min)", width="small", format="%,.0f"),
            },
            hide_index=True,
        )

        st.subheader("Total views by channel (top 20)")
        top_total_views_df = channel_ls_summary.head(20)  # already sorted by total_views
        total_views_chart = (
            alt.Chart(top_total_views_df)
            .mark_bar(color="#2EC4B6")
            .encode(
                x=alt.X("total_views:Q", title="Total views"),
                y=alt.Y("channel_title:N", title="Channel", sort="-x"),
                tooltip=["channel_title", "livestreams", "total_views", "avg_views"],
            )
        )
        st.altair_chart(total_views_chart, width="stretch")

        st.subheader("Livestream count by channel (top 20)")
        top_count_df = channel_ls_summary.sort_values("livestreams", ascending=False).head(20)
        count_chart = (
            alt.Chart(top_count_df)
            .mark_bar(color="#6A4C93")
            .encode(
                x=alt.X("livestreams:Q", title="Livestreams"),
                y=alt.Y("channel_title:N", title="Channel", sort="-x"),
                tooltip=["channel_title", "livestreams", "total_views", "avg_views"],
            )
        )
        st.altair_chart(count_chart, width="stretch")

        st.subheader("Avg. duration by channel (top 20)")
        duration_df = channel_ls_summary.dropna(subset=["avg_duration_seconds"]).copy()
        duration_df["avg_duration_minutes"] = duration_df["avg_duration_seconds"] / 60
        duration_df = duration_df.sort_values("avg_duration_minutes", ascending=False).head(20)

        if duration_df.empty:
            st.info("No channels with a recorded livestream duration yet.")
        else:
            duration_chart = (
                alt.Chart(duration_df)
                .mark_bar(color="#FF6B6B")
                .encode(
                    x=alt.X("avg_duration_minutes:Q", title="Avg. duration (min)"),
                    y=alt.Y("channel_title:N", title="Channel", sort="-x"),
                    tooltip=["channel_title", "livestreams", "avg_duration_minutes"],
                )
            )
            st.altair_chart(duration_chart, width="stretch")

        st.subheader("Avg. views by channel (top 20)")

        top_views_chart_df = channel_ls_summary.sort_values("avg_views", ascending=False).head(20)
        views_chart = (
            alt.Chart(top_views_chart_df)
            .mark_bar(color="#FFC145")
            .encode(
                x=alt.X("avg_views:Q", title="Avg. views"),
                y=alt.Y("channel_title:N", title="Channel", sort="-x"),
                tooltip=["channel_title", "livestreams", "avg_views", "total_views"],
            )
        )
        st.altair_chart(views_chart, width="stretch")

        st.subheader("Duration vs. views")
        scatter_df = livestream_videos.dropna(subset=["stream_duration_seconds"]).copy()
        scatter_df["duration_minutes"] = scatter_df["stream_duration_seconds"] / 60

        if scatter_df.empty:
            st.info("No livestreams with a recorded duration yet -- nothing to plot here.")
        else:
            scatter_chart = (
                alt.Chart(scatter_df)
                .mark_circle(color="#FFC145", opacity=0.6, size=60)
                .encode(
                    x=alt.X("duration_minutes:Q", title="Duration (min)"),
                    y=alt.Y("view_count:Q", title="Views", scale=alt.Scale(type="symlog")),
                    tooltip=["title", "channel_title", "duration_minutes", "view_count"],
                )
            )
            st.altair_chart(scatter_chart, width="stretch")

with tab4:
    st.subheader("Channels Overview")
    channel_summary_sorted = channels[
        ["title", "category", "subscriber_count", "view_count", "video_count", "channel_id"]
    ].sort_values("view_count", ascending=False).copy()
    channel_summary_sorted["url"] = "https://www.youtube.com/channel/" + channel_summary_sorted["channel_id"]
    st.dataframe(
        channel_summary_sorted[["title", "url", "view_count", "subscriber_count", "video_count", "category"]],
        column_config={
            "title": st.column_config.TextColumn("Channel", width="medium"),
            "url": st.column_config.LinkColumn("Visit", display_text="Open ↗", width="small"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "subscriber_count": st.column_config.NumberColumn("Subscribers", width="small", format="%,d"),
            "view_count": st.column_config.NumberColumn("Total views", width="small", format="%,d"),
            "video_count": st.column_config.NumberColumn("Total videos", width="small", format="%,d"),
        },
        hide_index=True,
    )

# with tab5:
#     st.subheader("Performance by content theme")
#
#     available_methods = themes["method"].unique().tolist()
#     if not available_methods:
#         st.info("No theme data yet. Run theme_extraction.py to generate themes.")
#     else:
#         method_counts = themes["method"].value_counts()
#         default_method = method_counts.idxmax()
#
#         method_choice = st.radio(
#             "Theme source",
#             available_methods,
#             index=available_methods.index(default_method),
#             horizontal=True,
#             format_func=lambda m: m.capitalize() if m != "llm" else "LLM",
#             help="LLM themes are more specific; clustering themes are faster but broader.",
#         )
#
#         theme_data = get_theme_data(filtered, themes, method_choice)
#
#         if theme_data.empty:
#             st.info(f"No '{method_choice}' theme data available for the currently filtered channels.")
#         else:
#             st.caption(f"{len(theme_data):,} of {len(filtered):,} filtered videos have a '{method_choice}' theme assigned.")
#
#         theme_summary = (
#             theme_data.groupby("theme_label")
#             .agg(videos=("video_id", "count"), avg_views=("view_count", "mean"))
#             .reset_index()
#             .sort_values("avg_views", ascending=False)
#         )
#
#         min_videos = st.slider(
#             "Minimum videos per theme (filters out one-off/noisy themes)",
#             min_value=1, max_value=20, value=3,
#         )
#         theme_summary = theme_summary[theme_summary["videos"] >= min_videos]
#
#         if theme_summary.empty:
#             st.warning(f"No themes have at least {min_videos} videos. Try lowering the minimum.")
#         else:
#             st.subheader(f"Avg. views by theme (top 20, min {min_videos} videos)")
#             top_themes_chart_df = theme_summary.head(20)
#             theme_chart = (
#                 alt.Chart(top_themes_chart_df)
#                 .mark_bar(color="#2EC4B6")
#                 .encode(
#                     x=alt.X("avg_views:Q", title="Avg. views"),
#                     y=alt.Y("theme_label:N", title="Theme", sort="-x"),
#                     tooltip=["theme_label", "videos", "avg_views"],
#                 )
#             )
#             st.altair_chart(theme_chart, width="stretch")
#
#             st.subheader("Videos by theme")
#             theme_options = sorted(theme_data["theme_label"].unique())
#             selected_theme = st.selectbox("Choose a theme to inspect", theme_options)
#
#             theme_videos = theme_data[theme_data["theme_label"] == selected_theme].copy()
#             theme_videos = theme_videos.sort_values("view_count", ascending=False)
#             theme_videos["url"] = "https://www.youtube.com/watch?v=" + theme_videos["video_id"]
#
#             st.caption(f"{len(theme_videos):,} video(s) labeled '{selected_theme}'")
#             st.dataframe(
#                 theme_videos[["title", "channel_title", "url", "content_type", "view_count"]],
#                 column_config={
#                     "title": st.column_config.TextColumn("Title", width="large"),
#                     "channel_title": st.column_config.TextColumn("Channel", width="medium"),
#                     "url": st.column_config.LinkColumn("Watch", display_text="Open ↗", width="small"),
#                     "content_type": st.column_config.TextColumn("Type", width="small"),
#                     "view_count": st.column_config.NumberColumn("Views", width="small", format="%,d"),
#                 },
#                 hide_index=True,
#             )