import datetime as dt

import requests

from xp_model import expected_points, minutes_probability

BASE_URL = "https://fantasy.premierleague.com/api"


def get_bootstrap_static() -> dict:
    resp = requests.get(f"{BASE_URL}/bootstrap-static/", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_fixtures(event: int | None = None) -> list[dict]:
    params = {"event": event} if event else {}
    resp = requests.get(f"{BASE_URL}/fixtures/", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_entry_picks(team_id: int, event: int) -> dict:
    resp = requests.get(
        f"{BASE_URL}/entry/{team_id}/event/{event}/picks/", timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def get_next_event(events: list[dict]) -> dict:
    return next(e for e in events if e["is_next"])


def get_current_event(events: list[dict]) -> dict | None:
    return next((e for e in events if e["is_current"]), None)


def hours_until_deadline(deadline_time: str) -> float:
    deadline = dt.datetime.fromisoformat(deadline_time.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    return (deadline - now).total_seconds() / 3600


def get_entry_snapshot(team_id: int, events: list[dict]) -> dict | None:
    """Full picks payload (squad + bank/value), tried against the next GW first
    (your saved-but-not-yet-locked squad) then the current GW as a fallback."""
    next_event = get_next_event(events)
    current_event = get_current_event(events)
    for event_id in (next_event["id"], current_event["id"] if current_event else None):
        if event_id is None:
            continue
        try:
            return get_entry_picks(team_id, event_id)
        except Exception:
            continue
    return None


def build_player_pool(data: dict, gw_fixtures: list[dict], squad_ids: set[int] | None = None) -> list[dict]:
    elements = data["elements"]
    teams = {t["id"]: t["name"] for t in data["teams"]}
    positions = {p["id"]: p["singular_name_short"] for p in data["element_types"]}

    pool = []
    for p in elements:
        if p["status"] == "u":  # left the league / not returning
            continue
        if squad_ids is not None and p["id"] not in squad_ids:
            continue
        pool.append(
            {
                "id": p["id"],
                "name": f"{p['first_name']} {p['second_name']}",
                "team": teams[p["team"]],
                "position": positions[p["element_type"]],
                "now_cost": p["now_cost"],
                "xp": round(expected_points(p, gw_fixtures), 2),
                "minutes_probability": minutes_probability(p),
            }
        )
    return pool
