# YouTube Channel Analytics Pipeline

A small end-to-end data pipeline: pulls channel + video data from the YouTube
Data API, lands it in SQLite, and visualizes performance — upload activity,
top content, engagement, and content-length trends — in an interactive
dashboard. Shorts vs. long-form is just one lens among several, not the
whole point.

This mirrors the kind of analysis you already do in Metabase/ClickHouse —
the difference is you're now owning the whole chain: ingestion, storage,
transformation, and presentation.

---

## Saturday: get data flowing

### 1. Get a YouTube Data API key (~15 min)
1. Go to https://console.cloud.google.com/
2. Create a new project (top left dropdown -> New Project)
3. In the search bar, find "YouTube Data API v3" -> click **Enable**
4. Go to **APIs & Services -> Credentials -> Create Credentials -> API key**
5. Copy the key

### 2. Set up the project (~10 min)
```bash
# unzip/cd into this folder, then:
python3 -m venv venv
source venv/bin/activate        # on Mac
pip install -r requirements.txt

cp .env.example .env
# open .env and paste your API key in
```

### 3. Pick some channels and pull data (~30-60 min)
Find channel IDs (they start with `UC...`) via a channel's About page,
or a tool like https://commentpicker.com/youtube-channel-id.php.
Pick 2-4 channels you find interesting — could even be a couple from the
Moonbug portfolio if they're public, or any channels you like.

```bash
python fetch_data.py UCxxxxxxxxxxxxxxxxxxxxxx UCyyyyyyyyyyyyyyyyyyyyyy
```

This creates `youtube_data.db` with two tables: `channels` and `videos`.
Watch it print progress as it fetches each channel.

**Checkpoint for Saturday:** you should be able to open `youtube_data.db`
(e.g. with the free "DB Browser for SQLite" app, or `sqlite3 youtube_data.db`
in the terminal) and see real rows of video data with views, likes, duration.

Try a query directly against it, just like you would in Metabase:
```sql
SELECT title, view_count, duration_seconds, is_short
FROM videos
ORDER BY view_count DESC
LIMIT 10;
```

---

## Sunday: transform and visualize

### 4. Explore and sanity-check the data (~30 min)
Open a Python shell or notebook and poke around:
```python
import sqlite3, pandas as pd
conn = sqlite3.connect("youtube_data.db")
df = pd.read_sql("SELECT * FROM videos", conn)
df.groupby("is_short")["view_count"].describe()
```
This is a good moment to decide if anything looks off (e.g. a channel with
very few videos, or Shorts miscategorized) before building on top of it.

### 5. Run the dashboard (~15 min to launch, then iterate)
```bash
streamlit run dashboard.py
```
This opens in your browser. It gives you four tabs:
- **Upload activity** — uploads and total views by month
- **Top content** — top videos by views and separately by engagement rate
- **Engagement** — views vs. engagement scatter plot (with outlier
  filtering, like your Metabase scatter queries), and average engagement
  by channel
- **Content length** — average views by duration bucket (Shorts are one
  bucket among several here, not the headline)

Plus a channel-level summary table at the bottom.

### 6. Make it yours (~rest of Sunday)
Pick 1-2 extensions that would make this feel like *your* analysis rather
than a template — this is the part worth highlighting when you talk about
it:
- Add a "views per day since published" metric (normalizes for recency)
- Break down performance by upload day-of-week or time-of-day
- Compare how a channel's content mix (Shorts vs. long-form vs. mid-length)
  has shifted over time
- Write 3-4 sentences of commentary on what the data shows — the same
  skill as your dashboard commentary at work, just on data you pulled
  yourself

### 7. Wrap up
- Push it to a public GitHub repo (this matters — it's the artifact you
  actually show people)
- Write a short README section of your own: what you built, what you'd
  add with more time, one interesting finding from the data
- Optional: deploy the dashboard for free on Streamlit Community Cloud
  (streamlit.io/cloud) so you have a live link, not just code

---

## Why this project specifically

- It proves you can build the pipeline, not just query one someone else
  built — that's the actual gap between "analyst" and "data engineer"
- It's grounded in something you already understand deeply (YouTube/Shorts
  data), so you can talk about it fluently
- It touches API integration, a relational database, data transformation,
  and a front end — a legitimate cross-section of a data engineering role
