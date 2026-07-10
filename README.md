# YouTube Channel Analytics

An end-to-end data pipeline and interactive dashboard for tracking YouTube channel performance. Pulls channel and video-level data from the YouTube Data API, stores it in SQLite, and visualizes upload activity, top content, and content-length trends through a Streamlit dashboard.

Built to analyze content strategy across multiple channels — upload frequency, Shorts vs. long-form mix, and view performance — with support for bulk channel management and category tagging.

## Features

- **Automated data pipeline** — pulls channel stats and recent video metadata (views, likes, duration, publish date) via the YouTube Data API v3
- **Rolling 90-day window** — fetches videos published in the last 90 days per channel, rather than a fixed video count, for fair comparison across channels with different upload frequencies
- **Bulk channel management** — add channels in bulk via a text file, with category tagging (e.g. cartoon, live action, mixed) for filtering
- **Interactive dashboard** — four views covering upload activity, top-performing content, content-length breakdown, and a channel-level summary
- **Resilient fetching** — handles edge cases like live streams/premieres with no fixed duration, and skips gracefully rather than failing the whole run

## Tech stack

- **Python** — data pipeline and transformation logic
- **YouTube Data API v3** — source data
- **SQLite** — local storage
- **pandas** — data wrangling
- **Streamlit + Altair** — interactive dashboard and charts

## Setup

### Prerequisites
- Python 3.10+
- A Google Cloud project with the YouTube Data API v3 enabled ([console.cloud.google.com](https://console.cloud.google.com))

### Installation

```bash
git clone <this-repo-url>
cd <repo-folder>
python3 -m venv venv
source venv/bin/activate     # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### API key

1. In [Google Cloud Console](https://console.cloud.google.com), enable the **YouTube Data API v3** for your project
2. Create an API key under **APIs & Services → Credentials**
3. Copy `.env.example` to `.env` and add your key:

```
YOUTUBE_API_KEY=your_api_key_here
```

## Usage

### Fetching data

Add channel IDs to `channels.txt`, one per line, each tagged with a category:

```
UCxxxxxxxxxxxxxxxxxxxxxx,cartoon
UCyyyyyyyyyyyyyyyyyyyyyy,live action
UCzzzzzzzzzzzzzzzzzzzzzz,mixed
```

Then run:

```bash
python fetch_data.py --file channels.txt
```

This creates/updates `youtube_data.db` with two tables: `channels` and `videos`. Re-running the same command later refreshes view counts on existing videos and adds any new ones.

A single channel can also be fetched directly without a file:

```bash
python fetch_data.py <channel_id>
```

### Running the dashboard

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501` with four tabs:

- **Upload activity** — uploads and total views over time, split by Shorts vs. long-form, plus upload mix by channel
- **Top content** — top 50 videos by views, with direct links to each
- **Content length** — average views by duration bucket
- **Channel summary** — subscriber counts, total views, and video counts per channel

The sidebar supports filtering by category and searching/selecting individual channels, designed to scale to 100+ channels.

## Project structure

```
.
├── fetch_data.py          # pulls data from the YouTube API into SQLite
├── dashboard.py            # Streamlit dashboard
├── channels.txt             # channel IDs + categories to fetch (not tracked if private)
├── channels.example.txt   # example format
├── requirements.txt
├── .env.example
└── youtube_data.db         # SQLite database (generated)
```

## Notes and limitations

- **Lifetime view counts, not time-windowed.** The YouTube Data API only returns cumulative views, likes, and comments — not performance over a specific period. A video's stats reflect its entire time live, not just the last 90 days.
- **No watch time or audience retention data.** These metrics live in the YouTube Analytics API, which requires OAuth as the channel owner — not available for arbitrary public channels.
- **Some videos may be geo-restricted or region-locked**, meaning the data may reference a video that isn't viewable from your location.
- **Comments are frequently disabled on kids' content** (COPPA compliance), which naturally suppresses comment counts for that category.