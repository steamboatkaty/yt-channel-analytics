"""
fetch_data.py

Pulls channel + video-level data from the YouTube Data API v3 and lands it
in a local SQLite database (raw, minimally transformed — that happens in
transform.py / the dashboard).

Usage:
    python fetch_data.py UCxxxxxxxx UCyyyyyyyy
    (pass one or more YouTube channel IDs as arguments)

Finding a channel ID:
    Go to the channel's page -> "..." or About -> Share -> Copy channel ID
    (it starts with UC...). Or use https://commentpicker.com/youtube-channel-id.php
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta

from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = "youtube_data.db"

DAYS_LOOKBACK = 90  # fetch videos published within this many days, per channel

def load_channel_ids_from_file(path: str) -> list:
    """
    Read one channel ID per line, skipping blanks and #-comments.
    Every line must include a category after a comma, e.g.:
        UCxxxxxxxx,cartoon
    A line with no category (or an empty one) raises an error rather than
    silently defaulting, since every channel is expected to be tagged.
    Returns a list of (channel_id, category) tuples.
    """
    if not os.path.exists(path):
        sys.exit(f"Channel ID file not found: {path}")

    entries = []
    with open(path) as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                sys.exit(
                    f"{path}, line {line_num}: missing category. "
                    f"Expected 'channel_id,category', got: {line!r}"
                )
            channel_id, category = line.split(",", 1)
            channel_id = channel_id.strip()
            category = category.strip()
            if not category:
                sys.exit(f"{path}, line {line_num}: empty category for {channel_id}")
            entries.append((channel_id, category))
    return entries

def get_client():
    if not API_KEY:
        sys.exit("Missing YOUTUBE_API_KEY. Copy .env.example to .env and add your key.")
    return build("youtube", "v3", developerKey=API_KEY)


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            title TEXT,
            subscriber_count INTEGER,
            view_count INTEGER,
            video_count INTEGER,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            title TEXT,
            published_at TEXT,
            duration_seconds INTEGER,
            is_short INTEGER,
            view_count INTEGER,
            like_count INTEGER,
            comment_count INTEGER,
            fetched_at TEXT
        );
        """

    )
    try:
        conn.execute("ALTER TABLE channels ADD COLUMN category TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()


def parse_iso8601_duration(duration: str) -> int:
    """Convert YouTube's ISO 8601 duration (e.g. 'PT1M30S') to seconds."""
    import re

    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration
    )
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def fetch_channel(youtube, channel_id: str) -> dict:
    resp = youtube.channels().list(
        part="snippet,statistics,contentDetails", id=channel_id
    ).execute()

    if not resp["items"]:
        raise ValueError(f"No channel found for ID {channel_id}")

    item = resp["items"][0]
    return {
        "channel_id": channel_id,
        "title": item["snippet"]["title"],
        "subscriber_count": int(item["statistics"].get("subscriberCount", 0)),
        "view_count": int(item["statistics"].get("viewCount", 0)),
        "video_count": int(item["statistics"].get("videoCount", 0)),
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def fetch_video_ids_since(youtube, playlist_id: str, days: int = DAYS_LOOKBACK, max_videos: int = 500) -> list:
    """
    Walk a channel's uploads playlist (newest first) and collect video IDs
    published within the last `days` days. Stops as soon as it hits a video
    older than the cutoff, or after `max_videos` as a safety cap for very
    high-volume channels.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    video_ids = []
    next_page_token = None

    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        ).execute()

        stop = False
        for item in resp["items"]:
            published_str = item["contentDetails"].get("videoPublishedAt")
            if published_str:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                if published < cutoff:
                    stop = True
                    break
            video_ids.append(item["contentDetails"]["videoId"])
            if len(video_ids) >= max_videos:
                stop = True
                break

        next_page_token = resp.get("nextPageToken")
        if stop or not next_page_token:
            break

    return video_ids


def fetch_video_details(youtube, video_ids: list) -> list:
    """
    Batch-fetch stats + duration for up to 50 video IDs at a time.

    Live streams and premieres sometimes have no "duration" field (or a
    zero-length one) until they finish — those are skipped rather than
    crashing the whole fetch.
    """
    videos = []
    skipped = 0
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(batch)
        ).execute()

        for item in resp["items"]:
            duration_str = item.get("contentDetails", {}).get("duration")
            if not duration_str:
                skipped += 1
                continue

            duration_seconds = parse_iso8601_duration(duration_str)
            videos.append(
                {
                    "video_id": item["id"],
                    "channel_id": item["snippet"]["channelId"],
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                    "duration_seconds": duration_seconds,
                    "is_short": 1 if duration_seconds <= 60 else 0,
                    "view_count": int(item["statistics"].get("viewCount", 0)),
                    "like_count": int(item["statistics"].get("likeCount", 0)),
                    "comment_count": int(item["statistics"].get("commentCount", 0)),
                }
            )
    if skipped:
        print(f"  (skipped {skipped} video(s) with no fixed duration, e.g. live/premiere)")
    return videos


def main():
    if len(sys.argv) < 2:
        sys.exit(
            "Usage:\n"
            "  python fetch_data.py <channel_id_1> [channel_id_2 ...]\n"
            "  python fetch_data.py --file channels.txt"
        )

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            sys.exit("Usage: python fetch_data.py --file channels.txt")
        channel_entries = load_channel_ids_from_file(sys.argv[2])
        if not channel_entries:
            sys.exit(f"No channel IDs found in {sys.argv[2]}")
    else:
        channel_entries = [(cid, "Uncategorized") for cid in sys.argv[1:]]

    print(f"Fetching {len(channel_entries)} channel(s)...\n")
    youtube = get_client()
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    now = datetime.now(timezone.utc).isoformat()

    for channel_id, category in channel_entries:
        print(f"Fetching channel {channel_id} ({category})...")
        channel = fetch_channel(youtube, channel_id)

        conn.execute(
            """INSERT OR REPLACE INTO channels
               (channel_id, title, subscriber_count, view_count, video_count, category, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                channel["channel_id"],
                channel["title"],
                channel["subscriber_count"],
                channel["view_count"],
                channel["video_count"],
                category,
                now,
            ),
        )

        print(f"  Fetching video IDs from the last {DAYS_LOOKBACK} days...")
        video_ids = fetch_video_ids_since(youtube, channel["uploads_playlist_id"])

        print(f"  Fetching details for {len(video_ids)} videos...")
        videos = fetch_video_details(youtube, video_ids)

        for v in videos:
            conn.execute(
                """INSERT OR REPLACE INTO videos
                   (video_id, channel_id, title, published_at, duration_seconds,
                    is_short, view_count, like_count, comment_count, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    v["video_id"],
                    v["channel_id"],
                    v["title"],
                    v["published_at"],
                    v["duration_seconds"],
                    v["is_short"],
                    v["view_count"],
                    v["like_count"],
                    v["comment_count"],
                    now,
                ),
            )

        conn.commit()
        print(f"  Done: {channel['title']} ({len(videos)} videos saved)\n")

    conn.close()
    print(f"All data saved to {DB_PATH}")


if __name__ == "__main__":
    main()
