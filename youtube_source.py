"""
Pulls transcripts from configured YouTube creators' latest uploads and adds
them, chunked, to the local knowledge store that chat.py/knowledge_base.py
read from -- so the chat assistant can be asked about what a creator said
in their latest video, grounded in the actual transcript text.

Requires YOUTUBE_API_KEY (free, from Google Cloud Console -- enable
"YouTube Data API v3", create an API key, no billing needed for the free
quota). Transcript fetching itself needs no key.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv

load_dotenv()

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

API_BASE = "https://www.googleapis.com/youtube/v3"

CHANNELS = [
    {"handle": "FPLHarry"},
    {"handle": "FPLRaptor"},
    {"handle": "FPLMate"},
    {"handle": "LetsTalkFPL"},
]

CHANNEL_CACHE_PATH = Path("youtube_channels_cache.json")
LOG_PATH = Path("video_sources_log.csv")
KNOWLEDGE_PATH = Path("video_knowledge.json")

MAX_VIDEOS_PER_CHANNEL = 2
CHUNK_WORDS = 250
CHUNK_OVERLAP_WORDS = 40


def _load_channel_cache() -> dict:
    if CHANNEL_CACHE_PATH.exists():
        return json.loads(CHANNEL_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_channel_cache(cache: dict) -> None:
    CHANNEL_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def resolve_channel(handle: str, api_key: str, cache: dict) -> dict:
    """Resolves a @handle to {channel_id, uploads_playlist_id, name}, caching
    the result locally so this API call (which counts against quota) only
    happens once per channel, not once per run."""
    if handle in cache:
        return cache[handle]

    resp = requests.get(
        f"{API_BASE}/channels",
        params={"part": "id,snippet,contentDetails", "forHandle": handle, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"No YouTube channel found for handle '@{handle}'.")

    item = items[0]
    entry = {
        "channel_id": item["id"],
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
        "name": item["snippet"]["title"],
    }
    cache[handle] = entry
    return entry


def get_recent_videos(uploads_playlist_id: str, api_key: str, max_results: int) -> list[dict]:
    resp = requests.get(
        f"{API_BASE}/playlistItems",
        params={"part": "snippet", "playlistId": uploads_playlist_id, "maxResults": max_results, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        snippet = item["snippet"]
        videos.append(
            {
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "published_at": snippet["publishedAt"],
            }
        )
    return videos


class TranscriptTemporarilyUnavailable(Exception):
    """Raised for anything that isn't a definitive "this video will never
    have a transcript" (e.g. a livestream that hasn't started yet, a
    transient network error). Callers should NOT mark the video as ingested
    for this -- it should be retried on a future run."""


def get_transcript_text(video_id: str) -> str | None:
    """Returns the transcript text, or None if this video will never have
    one (captions disabled / no transcript exists at all -- permanent, safe
    to stop retrying). Raises TranscriptTemporarilyUnavailable for anything
    else."""
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id)
        return " ".join(seg.text for seg in transcript)
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception as e:
        raise TranscriptTemporarilyUnavailable(str(e)) from e


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap_words: int = CHUNK_OVERLAP_WORDS) -> list[str]:
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    if not words:
        return []
    chunks = []
    step = max(chunk_words - overlap_words, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk:
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def already_ingested(video_id: str) -> bool:
    if not LOG_PATH.exists():
        return False
    with LOG_PATH.open(newline="", encoding="utf-8") as f:
        return any(row["video_id"] == video_id for row in csv.DictReader(f))


def log_ingested(video: dict, channel_name: str, chunk_count: int) -> None:
    import datetime as dt

    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["date_ingested", "channel", "title", "video_id", "published_at", "chunk_count"])
        writer.writerow([dt.date.today().isoformat(), channel_name, video["title"], video["video_id"], video["published_at"], chunk_count])


def load_knowledge() -> list[dict]:
    if KNOWLEDGE_PATH.exists():
        return json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    return []


def save_knowledge(docs: list[dict]) -> None:
    KNOWLEDGE_PATH.write_text(json.dumps(docs, indent=2, ensure_ascii=False), encoding="utf-8")


def ingest_all(api_key: str) -> int:
    cache = _load_channel_cache()
    knowledge = load_knowledge()
    new_chunk_count = 0

    for entry in CHANNELS:
        handle = entry["handle"]
        try:
            channel = resolve_channel(handle, api_key, cache)
        except Exception as e:
            print(f"Could not resolve @{handle}: {e}")
            continue

        print(f"Checking @{handle} ({channel['name']})...")
        try:
            videos = get_recent_videos(channel["uploads_playlist_id"], api_key, MAX_VIDEOS_PER_CHANNEL)
        except Exception as e:
            print(f"  Could not fetch recent videos for @{handle}: {e}")
            continue

        for video in videos:
            if already_ingested(video["video_id"]):
                continue

            print(f"  New video: {video['title']}")
            try:
                text = get_transcript_text(video["video_id"])
            except TranscriptTemporarilyUnavailable as e:
                print(f"  Transcript not available yet ({e}); will retry on a future run.")
                continue  # not logged as ingested -- deliberately retried next run

            if not text:
                print("  No transcript available (captions disabled), skipping permanently.")
                log_ingested(video, channel["name"], 0)
                continue

            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                knowledge.append(
                    {
                        "id": f"video-{video['video_id']}-{i}",
                        "channel": channel["name"],
                        "title": video["title"],
                        "video_id": video["video_id"],
                        "published_at": video["published_at"],
                        "text": chunk,
                    }
                )
            log_ingested(video, channel["name"], len(chunks))
            new_chunk_count += len(chunks)
            print(f"  Added {len(chunks)} chunks.")

    _save_channel_cache(cache)
    save_knowledge(knowledge)
    return new_chunk_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest transcripts from configured YouTube creators.")
    parser.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY is not set. See .env.example.")
        return

    new_chunks = ingest_all(api_key)
    print(f"\nDone. {new_chunks} new chunks added to {KNOWLEDGE_PATH}.")


if __name__ == "__main__":
    main()
