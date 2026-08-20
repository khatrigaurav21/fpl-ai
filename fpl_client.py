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


def get_entry_history(team_id: int) -> dict:
    resp = requests.get(f"{BASE_URL}/entry/{team_id}/history/", timeout=10)
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


def get_team_fixtures(team_id: int, gw_fixtures: list[dict], short_names: dict[int, str]) -> list[dict]:
    """Opponent(s) for a team in one gameweek, as a list to handle double
    gameweeks -- empty list means a blank gameweek for that team."""
    result = []
    for f in gw_fixtures:
        if f["team_h"] == team_id:
            result.append({"opponent": short_names[f["team_a"]], "is_home": True})
        elif f["team_a"] == team_id:
            result.append({"opponent": short_names[f["team_h"]], "is_home": False})
    return result


def build_player_pool(data: dict, gw_fixtures: list[dict], squad_ids: set[int] | None = None) -> list[dict]:
    elements = data["elements"]
    teams = {t["id"]: t["name"] for t in data["teams"]}
    short_names = {t["id"]: t["short_name"] for t in data["teams"]}
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
                "web_name": p["web_name"],
                "team": teams[p["team"]],
                "position": positions[p["element_type"]],
                "now_cost": p["now_cost"],
                "xp": round(expected_points(p, gw_fixtures), 2),
                "minutes_probability": minutes_probability(p),
                "fixtures": get_team_fixtures(p["team"], gw_fixtures, short_names),
            }
        )
    return pool
