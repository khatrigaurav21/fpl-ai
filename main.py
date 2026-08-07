import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from captaincy import pick_captain_vice, rank_candidates
from fpl_client import get_bootstrap_static, get_entry_picks, get_fixtures
from xp_model import expected_points, minutes_probability

LOG_PATH = Path("predictions_log.csv")


def get_next_event(events: list[dict]) -> dict:
    return next(e for e in events if e["is_next"])


def get_current_event(events: list[dict]) -> dict | None:
    return next((e for e in events if e["is_current"]), None)


def get_squad_ids(team_id: int, events: list[dict]) -> set[int] | None:
    next_event = get_next_event(events)
    for event_id in (next_event["id"], get_current_event(events) and get_current_event(events)["id"]):
        if event_id is None:
            continue
        try:
            picks = get_entry_picks(team_id, event_id)
            return {p["element"] for p in picks["picks"]}
        except Exception:
            continue
    print(f"Warning: could not fetch squad for team {team_id}; using full player pool.")
    return None


def build_player_pool(data: dict, gw_fixtures: list[dict], squad_ids: set[int] | None) -> list[dict]:
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
                "xp": round(expected_points(p, gw_fixtures), 2),
                "minutes_probability": minutes_probability(p),
            }
        )
    return pool


def log_prediction(gw: int, captain: dict, vice: dict) -> None:
    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(
                ["date_logged", "gameweek", "captain", "captain_xp", "vice", "vice_xp", "actual_captain_points"]
            )
        writer.writerow([dt.date.today().isoformat(), gw, captain["name"], captain["xp"], vice["name"], vice["xp"], ""])


def main() -> None:
    parser = argparse.ArgumentParser(description="Next-gameweek xP and captaincy recommendation.")
    parser.add_argument("--team-id", type=int, default=None, help="Your FPL team/entry ID, to rank only your squad.")
    parser.add_argument("--top-n", type=int, default=10, help="How many candidates to show.")
    args = parser.parse_args()

    data = get_bootstrap_static()
    next_gw = get_next_event(data["events"])
    fixtures = get_fixtures(event=next_gw["id"])

    squad_ids = get_squad_ids(args.team_id, data["events"]) if args.team_id else None

    pool = build_player_pool(data, fixtures, squad_ids)
    if not pool:
        print("No players found for this gameweek (blank gameweek for your squad, or bad team ID).")
        return

    ranked = rank_candidates(pool, top_n=args.top_n)
    captain, vice = pick_captain_vice(ranked)

    print(f"Gameweek {next_gw['id']} — {next_gw['name']}\n")
    print("Top candidates:")
    for p in ranked:
        print(f"  {p['name']:<25} {p['team']:<15} {p['position']:<4} xP={p['xp']:>5.2f}  minutes={p['minutes_probability']:.0%}")

    print(f"\nCaptain: {captain['name']} (xP={captain['xp']})")
    print(f"Vice:    {vice['name']} (xP={vice['xp']})")

    log_prediction(next_gw["id"], captain, vice)
    print(f"\nLogged prediction to {LOG_PATH.resolve()}")


if __name__ == "__main__":
    main()
