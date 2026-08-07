import requests

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
