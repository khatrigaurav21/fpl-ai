import json
import re
from pathlib import Path

from captaincy import pick_captain_vice, rank_candidates, top_by_position
from fpl_client import build_player_pool, get_bootstrap_static, get_fixtures, get_next_event

VIDEO_KNOWLEDGE_PATH = Path("video_knowledge.json")


POSITION_SYNONYMS = {
    "GKP": {"gkp", "gk", "goalkeeper", "goalkeepers", "keeper", "keepers", "goalie"},
    "DEF": {"def", "defender", "defenders", "defence", "defense"},
    "MID": {"mid", "midfielder", "midfielders", "midfield"},
    "FWD": {"fwd", "forward", "forwards", "striker", "strikers", "attacker", "attackers"},
}


def _player_keywords(p: dict) -> set[str]:
    words = set(p["name"].lower().split()) | set(p["web_name"].lower().split())
    words.add(p["team"].lower())
    words |= POSITION_SYNONYMS.get(p["position"], {p["position"].lower()})
    return words


MODEL_SOURCE = "Our model"


def build_player_docs(pool: list[dict]) -> list[dict]:
    docs = []
    for p in pool:
        text = (
            f"{p['name']} ({p['web_name']}) plays for {p['team']} as a {p['position']}. "
            f"Price: £{p['now_cost'] / 10:.1f}m. "
            f"Projected points next gameweek: {p['xp']:.2f}. "
            f"Probability of playing: {p['minutes_probability']:.0%}."
        )
        docs.append({"id": f"player-{p['id']}", "keywords": _player_keywords(p), "text": text, "source": MODEL_SOURCE})
    return docs


def build_summary_docs(by_position: dict, captain: dict, vice: dict, gw: int) -> list[dict]:
    top_lines = []
    for pos, players in by_position.items():
        top_lines.append(f"{pos}: " + ", ".join(f"{p['name']} ({p['xp']:.2f} xP)" for p in players))

    return [
        {
            "id": "top-picks",
            "keywords": {"top", "best", "pick", "picks", "recommend", "recommendation"},
            "text": f"Top picks by position for GW{gw} (by projected points):\n" + "\n".join(top_lines),
            "source": MODEL_SOURCE,
        },
        {
            "id": "captain",
            "keywords": {"captain", "vice", "armband", "captaincy"},
            "text": (
                f"Recommended captain for GW{gw}: {captain['name']} (xP={captain['xp']:.2f}). "
                f"Recommended vice-captain: {vice['name']} (xP={vice['xp']:.2f})."
            ),
            "source": MODEL_SOURCE,
        },
    ]


def _video_keywords(title: str, channel: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", title.lower())) | set(re.findall(r"[a-z0-9]+", channel.lower()))
    words = {w for w in words if len(w) > 2}
    # FPL creators mix "GW1" and "gameweek 1" interchangeably in titles.
    # Without normalizing, a query using one form systematically buries every
    # chunk from every video whose title happens to use the other -- found
    # via a real query where an entire creator's 32 ingested chunks scored
    # below another creator's, purely because "GW1" != "gameweek" as tokens.
    if any(re.match(r"gw\d*$", w) for w in words) or "gameweek" in words:
        words.add("gameweek")
        words.add("gw")
    return words


def build_video_docs() -> list[dict]:
    """Loads transcript chunks ingested by youtube_source.py, if any. Each
    chunk becomes its own retrievable doc so chat can surface just the
    relevant part of a video, not the whole transcript at once."""
    if not VIDEO_KNOWLEDGE_PATH.exists():
        return []
    chunks = json.loads(VIDEO_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    docs = []
    for c in chunks:
        keywords = _video_keywords(c["title"], c["channel"])
        text = f"From {c['channel']}'s video \"{c['title']}\": {c['text']}"
        docs.append({"id": c["id"], "keywords": keywords, "text": text, "source": c["channel"]})
    return docs


def build_knowledge_base() -> tuple[list[dict], int]:
    data = get_bootstrap_static()
    next_gw = get_next_event(data["events"])
    fixtures = get_fixtures(event=next_gw["id"])
    pool = build_player_pool(data, fixtures)

    full_ranking = rank_candidates(pool, top_n=len(pool))
    captain, vice = pick_captain_vice(full_ranking)
    by_position = top_by_position(pool, n=5)

    docs = build_player_docs(pool)
    docs += build_summary_docs(by_position, captain, vice, next_gw["id"])
    docs += build_video_docs()
    return docs, next_gw["id"]


def _score(query_terms: set[str], doc: dict) -> int:
    keyword_hits = len(query_terms & doc.get("keywords", set()))
    text_hits = sum(1 for term in query_terms if len(term) > 2 and term in doc["text"].lower())
    return keyword_hits * 2 + text_hits


def retrieve(query: str, docs: list[dict], top_k: int = 8) -> list[dict]:
    """Keyword-overlap retrieval. Deliberately simple for v1 -- no embeddings,
    no vector store. Swapping this for semantic (embedding-based) retrieval is
    the natural next step once this baseline is proven useful."""
    query_terms = set(query.lower().replace("?", "").replace(",", "").split())

    scored = [(_score(query_terms, doc), doc) for doc in docs]
    scored = [(s, d) for s, d in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    always_include_ids = {"top-picks", "captain"}
    result, seen = [], set()
    for doc in docs:
        if doc["id"] in always_include_ids:
            result.append(doc)
            seen.add(doc["id"])
    for _, doc in scored:
        if doc["id"] not in seen:
            result.append(doc)
            seen.add(doc["id"])
        if len(result) >= top_k:
            break
    return result


def retrieve_by_source(query: str, docs: list[dict], top_k_per_source: int = 2) -> dict[str, list[dict]]:
    """Like retrieve(), but guarantees each source (our own model, plus each
    individually-named YouTube creator) its own retrieval slot rather than
    competing in one shared ranked list -- otherwise a source using different
    vocabulary than the query can get crowded out entirely by another, the
    exact bug found and fixed in retrieve() for a single-list ranking. A
    source is omitted entirely if it has no positive-scoring match, rather
    than forcing in irrelevant content."""
    query_terms = set(query.lower().replace("?", "").replace(",", "").split())

    by_source: dict[str, list[dict]] = {}
    for doc in docs:
        by_source.setdefault(doc.get("source", MODEL_SOURCE), []).append(doc)

    result: dict[str, list[dict]] = {}
    for source, source_docs in by_source.items():
        scored = [(_score(query_terms, doc), doc) for doc in source_docs]
        scored = [(s, d) for s, d in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [doc for _, doc in scored[:top_k_per_source]]
        if top:
            result[source] = top

    # The model's summary docs (top-picks, captain) are always relevant context
    # for a consensus view, regardless of keyword score.
    always_include = [doc for doc in docs if doc["id"] in {"top-picks", "captain"}]
    if always_include:
        other_model_docs = [d for d in result.get(MODEL_SOURCE, []) if d["id"] not in {"top-picks", "captain"}]
        result[MODEL_SOURCE] = always_include + other_model_docs

    return result
