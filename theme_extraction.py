"""
theme_extraction.py

Extracts content themes from video metadata using two different approaches:
1. TF-IDF + k-means clustering (unsupervised, no external API calls)
2. LLM-based categorization (Gemini)

Both sets of results are written to the video_themes table for comparison.

Usage:
    python theme_extraction.py --method clustering
    python theme_extraction.py --method llm
    python theme_extraction.py --method both
"""

import re
import sqlite3
from datetime import datetime, timezone

import pandas as pd

import os
import json
import time

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DB_PATH = "youtube_data.db"

THEME_VOCABULARY = [
    # Educational
    "learning numbers", "learning colors", "learning shapes", "learning the alphabet",
    "science facts", "animal facts", "life skills and safety", "vocabulary building",
    # Music and rhymes
    "nursery rhymes", "sing-along songs", "dance songs", "lullabies", "karaoke", "music"
    # Story formats
    "bedtime stories", "story time", "fairy tale", "read aloud", "puppet show",
    # Activities
    "pretend play", "cooking and baking", "arts and crafts",
    "science experiment", "magic tricks", "building and construction", "dancing",
    # Adventure / action
    "cops and robbers", "superhero action", "rescue mission", "mystery adventure",
    "space adventure", "treasure hunt", "obstacle course", "racing",
    # Comedy
    "slapstick comedy", "comedy cartoons", "awkward moments",
    # Animal content
    "jungle animals", "dogs", "cats", "farm animals",
    "sea animals", "insects", "dinosaurs", "birds", "animal cartoon",
    # Everyday life
    "family life", "sibling rivalry", "friendship story", "sharing and kindness",
    "learning emotions", "problem solving", "school",
    # Play and outings
    "water play", "beach day", "outdoor fun", "playground fun", "sports game",
    "birthday party", "sleepover", "travel adventure", "seasonal holiday",
    # Vehicles and toys
    "vehicles", "cars", "toy play", "toy unboxing", "dress-up roleplay",
]


def load_videos(conn) -> pd.DataFrame:
    """Load video text fields, joined with each video's channel title."""
    query = """
        SELECT v.video_id, v.title, v.description, v.tags, c.title AS channel_title
        FROM videos v
        JOIN channels c ON v.channel_id = c.channel_id
    """
    return pd.read_sql_query(query, conn)

def strip_channel_name(text: str, channel_title: str) -> str:
    """Remove any word that also appears in the channel's own title,
    so the channel's brand name doesn't dominate every video's document."""
    if not channel_title:
        return text
    channel_words = re.findall(r"\w+", channel_title.lower())
    for word in channel_words:
        if len(word) < 3:
            continue  # skip tiny/common words like "of", "tv" to avoid over-stripping
        text = re.sub(rf"\b{re.escape(word)}\b", "", text, flags=re.IGNORECASE)
    return text

def clean_text(text: str) -> str:
    """Strip URLs, newlines, and extra whitespace from raw video text."""
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"http\S+", "", text)  # full URLs starting with http(s)
    text = re.sub(r"\S+\.(com|co\.uk|net|org|tv|io)\S*", "", text, flags=re.IGNORECASE)  # bare domains
    text = re.sub(r"\s+", " ", text)  # collapse multiple spaces
    return text.strip()

def build_document(row: pd.Series) -> str:
    """
    Combine a video's title, description, and tags into a single text
    blob for theme extraction, with the channel's own name stripped out
    first so brand-name repetition doesn't dominate the clustering.
    """
    title = clean_text(row["title"])
    description = clean_text(row["description"])
    tags = (row["tags"] or "").replace(",", " ")

    combined = f"{title} {title} {description} {tags}"
    combined = strip_channel_name(combined, row["channel_title"])
    return combined

def cluster_videos(df: pd.DataFrame, n_clusters: int = 15):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans

    documents = df.apply(build_document, axis=1)

    custom_stop_words = list(TfidfVectorizer(stop_words="english").get_stop_words()) + [
        "shorts", "short", "video", "videos", "episode", "episodes",
    ]

    vectorizer = TfidfVectorizer(
        max_features=500,
        stop_words=custom_stop_words,
        min_df=2,
    )
    tfidf_matrix = vectorizer.fit_transform(documents)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = kmeans.fit_predict(tfidf_matrix)

    distances = kmeans.transform(tfidf_matrix)
    distance_to_own_cluster = [
        distances[i, cluster_labels[i]] for i in range(len(cluster_labels))
    ]

    return vectorizer, kmeans, cluster_labels, distance_to_own_cluster

def label_clusters(vectorizer, kmeans, n_terms: int = 3) -> dict:
    """
    For each cluster, find its top n_terms most distinctive words
    (based on the cluster's center in TF-IDF space) and join them into
    a readable label, e.g. "bluey, family, episodes".
    """
    terms = vectorizer.get_feature_names_out()
    labels = {}

    for cluster_id, center in enumerate(kmeans.cluster_centers_):
        top_indices = center.argsort()[::-1][:n_terms]
        top_terms = [terms[i] for i in top_indices]
        labels[cluster_id] = ", ".join(top_terms)

    return labels

def save_cluster_results(conn, video_ids, cluster_labels, distances, label_map):
    """Write clustering results into the video_themes table."""
    now = datetime.now(timezone.utc).isoformat()

    for video_id, cluster_id, distance in zip(video_ids, cluster_labels, distances):
        theme_label = label_map[cluster_id]
        conn.execute(
            """INSERT OR REPLACE INTO video_themes
               (video_id, method, theme_label, confidence, assigned_at)
               VALUES (?, ?, ?, ?, ?)""",
            (video_id, "clustering", theme_label, float(distance), now),
        )
    conn.commit()

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract content themes from video metadata.")
    parser.add_argument(
        "--method", choices=["clustering", "llm", "both"], default="clustering",
        help="Which theme extraction method to run (default: clustering)"
    )
    parser.add_argument(
        "--clusters", type=int, default=15, help="Number of clusters for k-means (default: 15)"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process this many videos (useful for testing --method llm)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Recategorize all videos with --method llm, even ones already done",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    print("Loading videos from database...")
    df = load_videos(conn)
    print(f"Loaded {len(df)} videos.")

    if args.method in ("clustering", "both"):
        print(f"Running TF-IDF + k-means clustering (k={args.clusters})...")
        vectorizer, kmeans, cluster_labels, distances = cluster_videos(df, n_clusters=args.clusters)

        print("Labeling clusters...")
        label_map = label_clusters(vectorizer, kmeans)
        for cluster_id, label in sorted(label_map.items()):
            count = (cluster_labels == cluster_id).sum()
            print(f"  Cluster {cluster_id}: {label} ({count} videos)")

        print("Saving clustering results to video_themes table...")
        save_cluster_results(conn, df["video_id"], cluster_labels, distances, label_map)

    if args.method in ("llm", "both"):
        print(f"Running LLM categorization{f' (limit={args.limit})' if args.limit else ''}...")
        run_llm_categorization(conn, df, limit=args.limit, force=args.force)

    conn.close()
    print("Done.")

def categorize_with_llm(model, title: str, description: str, tags: str, max_retries: int = 2) -> dict:
    """
    Ask Gemini to assign a theme label from THEME_VOCABULARY to a single
    video. Retries a couple of times on empty/failed responses before
    giving up, since the API is occasionally flaky.
    """
    vocab_list = "\n".join(f"- {t}" for t in THEME_VOCABULARY)

    prompt = f"""You are categorizing a children's YouTube video by content theme.

    Title: {title}
    Description: {description[:300]}
    Tags: {tags}

    Choose the SINGLE best-fitting theme from this fixed list:
    {vocab_list}

    Rules:
1. First identify what's actually happening in the video (an activity,
   subject, or format), not which show/character it's from.
2. Pick the closest match from the list above. Use the EXACT wording from
   the list -- do not invent variations or new phrasing.
3. Only respond with a theme NOT on the list if the video genuinely fits
   nothing above, and even then prefer the closest general match over a
   very specific new label. If you must invent one, prefix it with "other:".
4. "slapstick comedy" is for classic chase/prank/physical-comedy cartoons
   (e.g. Tom and Jerry, Looney Tunes). Use "comedy cartoons" only for
   other humor that isn't primarily physical/chase-based.
5. Don't default to a show's main character's species just because they
   appear in the video. Look at what the video is actually ABOUT.
   - "Whale Shark Bus Adventure" -> "sea animals" (the whale shark is the
     subject), even if the channel/show usually features a dog character.
   - A Bluey (dog character) video about a "Pony Ride" -> the pony is the
     actual subject, so consider "farm animals" or a specific animal
     match over defaulting to "dogs" just because Bluey is a dog.
   - Only use an animal category tied to the main character's species if
     the video's actual content is about that character being that animal
     (not just because they're technically a dog/cat in the show).
6. Titles are often structured as "[what the video is actually about] |
   [show/brand name/channel name]", with the descriptive part FIRST and
   the brand trailing after a pipe (|), dash, or colon. Weight the
   beginning of the title more heavily than the end when the two conflict
   -- the brand name at the end is often just channel branding, not the
   video's actual subject.
   7. If the video's core activity is a craft/creative task -- drawing, painting,
   decorating, building, baking -- use that activity's theme ("arts and crafts",
   "cooking and baking", "building and construction") even if a superhero,
   franchise character, or dramatic-sounding title is involved.
   - "Marinette draws a portrait of Adrien's dad" -> "arts and crafts"
     (drawing is the actual activity; ignore "Marinette"/Miraculous Ladybug
     branding and any implied drama in the title)
   - "Winnie the Pooh Cartoon Comes to Life" -> if the video is actually
     about a craft/drawing process, use "arts and crafts"; if it's really
     just a story/episode, use a story-format theme instead
   8. Judge the theme from the video's actual content and description, not
   just the most dramatic-sounding words in the title ("Relationship is
   Over?!", "Epic Battle", "Sneaky Surrender"). Titles are often written
   to sound more dramatic or urgent than the video's real content.
   9. Look for concrete activity/subject words in the title even when they're
   not the first word -- food/cooking words (treats, yummy, baking, cooking,
   recipe), dance/music words (dance, dancing, song), etc. should point
   directly to their matching theme, not a vaguer emotional/social theme.
   - "Yummy Treats | Sharing and Caring Moments" -> "cooking and baking"
     (the food content is the real subject; "sharing and caring" in the
     title is just a tagline, not the actual theme)
   - "Angelina Dance By The River | Full Episode" -> "dancing"
     (the word "Dance" directly names the activity -- don't default to a
     generic social/emotional theme when a specific activity is named)
     10. "problem solving" and "sharing and kindness" are OFTEN OVERUSED as
   default/safe choices -- only use them if the video is genuinely about
   a character working through a conflict or emotional lesson, not as a
   fallback when you're unsure. If the title contains ANY concrete,
   nameable subject (a food, an activity, an animal, a color/craft task,
   a sport, a vehicle), that concrete theme always wins over these two
   vaguer options.
   - "Cake and Colors Competition" -> "cooking and baking" (cake is a
     concrete, nameable subject; don't default to "problem solving")

    Respond with a JSON object in this exact format:
    {{"theme_label": "exact theme from the list above", "confidence": 0.0 to 1.0}}
    """

    last_error = "unknown"
    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
            result = json.loads(raw)
            return {
                "theme_label": result.get("theme_label", "unknown"),
                "confidence": float(result.get("confidence", 0.0)),
            }
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2)  # brief pause before retrying

    print(f"    LLM call failed after {max_retries + 1} attempts: {last_error}")
    return {"theme_label": None, "confidence": None}

def get_gemini_model():
    """Configure and return a Gemini model client, or exit with a clear
    error if the API key is missing."""
    if not GEMINI_API_KEY:
        raise SystemExit(
            "Missing GEMINI_API_KEY. Add it to your .env file before running --method llm."
        )
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(
        "gemini-flash-lite-latest",
        generation_config={"response_mime_type": "application/json"},
    )

def run_llm_categorization(conn, df: pd.DataFrame, limit: int = None, force: bool = False):
    """
    Run LLM categorization across videos in df, optionally limited to
    the first `limit` rows for testing. Saves results incrementally
    (one at a time) so partial progress isn't lost if it's interrupted.
    By default, skips videos that already have an 'llm' theme -- pass
    force=True to recategorize everything from scratch.
    """
    model = get_gemini_model()
    now = datetime.now(timezone.utc).isoformat()

    if not force:
        already_done = pd.read_sql(
            "SELECT video_id FROM video_themes WHERE method = 'llm'", conn
        )["video_id"].tolist()
        before_count = len(df)
        df = df[~df["video_id"].isin(already_done)]
        print(f"Skipping {before_count - len(df)} already-categorized videos, "
              f"{len(df)} remaining.")

    subset = df.head(limit) if limit else df

    for i, row in subset.iterrows():
        result = categorize_with_llm(model, row["title"], row["description"] or "", row["tags"] or "")

        if result["theme_label"] is not None:
            conn.execute(
                """INSERT OR REPLACE INTO video_themes
                   (video_id, method, theme_label, confidence, assigned_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["video_id"], "llm", result["theme_label"], result["confidence"], now),
            )
            conn.commit()
            print(f"  [{i+1}/{len(subset)}] {row['title'][:50]}... -> {result['theme_label']}")
        else:
            print(f"  [{i+1}/{len(subset)}] {row['title'][:50]}... -> FAILED, skipped")

        time.sleep(7)

if __name__ == "__main__":
    main()