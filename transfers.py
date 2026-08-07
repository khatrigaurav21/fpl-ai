import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fpl_client import (
    build_player_pool,
    get_bootstrap_static,
    get_entry_history,
    get_entry_snapshot,
    get_fixtures,
    get_next_event,
    hours_until_deadline,
)
from notify import send_ntfy

MAX_PER_CLUB = 3
HIT_COST = 4
MIN_MINUTES_PROBABILITY = 0.75
MAX_BANKED_TRANSFERS = 5

LOG_PATH = Path("transfer_suggestions_log.csv")


def compute_free_transfers(history: dict) -> int:
    """Replays FPL's free-transfer accrual rule across completed gameweeks.
    GW1 is unlimited squad-building and doesn't count. A gameweek where a
    chip that grants unlimited free transfers (wildcard/free hit) was active
    doesn't consume banked transfers either -- it just rolls over as if you
    hadn't moved."""
    unlimited_chip_events = {
        c["event"] for c in history.get("chips", []) if c["name"] in ("wildcard", "freehit")
    }
    free_transfers = 1
    for gw in history.get("current", [])[1:]:  # skip GW1
        if gw["event"] in unlimited_chip_events:
            transfers_made = 0
        else:
            transfers_made = gw["event_transfers"]
        used = min(transfers_made, free_transfers)
        free_transfers = min(MAX_BANKED_TRANSFERS, free_transfers - used + 1)
    return free_transfers


def already_suggested(gw: int) -> bool:
    if not LOG_PATH.exists():
        return False
    with LOG_PATH.open(newline="") as f:
        return any(row["gameweek"] == str(gw) for row in csv.DictReader(f))


def log_suggestions(gw: int, suggestions: list[dict]) -> bool:
    if already_suggested(gw):
        return False
    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["date_logged", "gameweek", "out", "in", "xp_gain", "hit", "net_gain", "cost"])
        for c in suggestions:
            writer.writerow(
                [dt.date.today().isoformat(), gw, c["out"]["name"], c["in"]["name"], c["xp_gain"], c["hit"], c["net_gain"], c["cost"]]
            )
    return True


def build_squad(pool_by_id: dict[int, dict], picks: list[dict]) -> list[dict]:
    squad = []
    for pick in picks:
        player = dict(pool_by_id[pick["element"]])
        player["selling_price"] = pick["selling_price"]
        squad.append(player)
    return squad


def suggest_transfers(
    squad: list[dict],
    full_pool: list[dict],
    bank: int,
    free_transfers: int,
    max_suggestions: int = 3,
) -> tuple[list[dict], int]:
    """Greedy, budget- and club-limit-aware transfer suggestions for the next
    gameweek only. Fixes the weakest squad player first, finds the best
    affordable, available, same-position replacement, and repeats. Hits are
    charged per-transfer beyond `free_transfers` and only kept if that specific
    swap's own xP gain outweighs the -4."""

    owned_ids = {p["id"] for p in squad}
    used_ids = set(owned_ids)

    pool_by_position: dict[str, list[dict]] = {}
    for p in full_pool:
        pool_by_position.setdefault(p["position"], []).append(p)
    for players in pool_by_position.values():
        players.sort(key=lambda p: p["xp"], reverse=True)

    club_counts: dict[str, int] = {}
    for p in squad:
        club_counts[p["team"]] = club_counts.get(p["team"], 0) + 1

    remaining_budget = bank
    candidates = []

    for out_player in sorted(squad, key=lambda p: p["xp"]):
        club_counts[out_player["team"]] -= 1

        best_in = None
        for candidate in pool_by_position.get(out_player["position"], []):
            if candidate["xp"] <= out_player["xp"]:
                break  # sorted descending; nothing further can improve on this
            if candidate["id"] in used_ids:
                continue
            if candidate["minutes_probability"] < MIN_MINUTES_PROBABILITY:
                continue
            cost = candidate["now_cost"] - out_player["selling_price"]
            if cost > remaining_budget:
                continue
            if club_counts.get(candidate["team"], 0) >= MAX_PER_CLUB:
                continue
            best_in = candidate
            break

        if best_in is None:
            club_counts[out_player["team"]] += 1  # revert; this player stays
            continue

        cost = best_in["now_cost"] - out_player["selling_price"]
        candidates.append(
            {
                "out": out_player,
                "in": best_in,
                "xp_gain": round(best_in["xp"] - out_player["xp"], 2),
                "cost": cost,
            }
        )
        remaining_budget -= cost
        used_ids.add(best_in["id"])
        club_counts[best_in["team"]] = club_counts.get(best_in["team"], 0) + 1

        if len(candidates) >= max_suggestions:
            break

    final = []
    budget_spent = 0
    for i, c in enumerate(candidates):
        hit = 0 if i < free_transfers else HIT_COST
        net_gain = round(c["xp_gain"] - hit, 2)
        if net_gain <= 0:
            break  # not worth it; later candidates only get worse
        c["hit"] = hit
        c["net_gain"] = net_gain
        final.append(c)
        budget_spent += c["cost"]

    return final, bank - budget_spent


def format_transfer(c: dict) -> str:
    hit_note = f" (-{c['hit']} hit)" if c["hit"] else " (free)"
    return (
        f"  OUT: {c['out']['name']:<25} (xP={c['out']['xp']:.2f})\n"
        f"  IN:  {c['in']['name']:<25} (xP={c['in']['xp']:.2f})\n"
        f"       net gain {c['net_gain']:+.2f}{hit_note}, cost £{c['cost'] / 10:+.1f}m"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Budget-aware transfer suggestions for the next gameweek.")
    parser.add_argument("--team-id", type=int, required=True, help="Your FPL team/entry ID.")
    parser.add_argument(
        "--free-transfers",
        type=int,
        default=None,
        help="How many free transfers you have. Auto-computed from your transfer history if omitted.",
    )
    parser.add_argument("--max-suggestions", type=int, default=3, help="Maximum number of transfers to suggest.")
    parser.add_argument("--notify", action="store_true", help="Send a push notification via ntfy.sh (requires NTFY_TOPIC env var).")
    parser.add_argument(
        "--deadline-window-hours",
        type=float,
        default=None,
        help="Only proceed if the next deadline is within this many hours. Meant for scheduled/cron runs.",
    )
    args = parser.parse_args()

    data = get_bootstrap_static()
    next_gw = get_next_event(data["events"])

    if args.deadline_window_hours is not None:
        hours_left = hours_until_deadline(next_gw["deadline_time"])
        if not (0 <= hours_left <= args.deadline_window_hours):
            print(f"GW{next_gw['id']} deadline is {hours_left:.1f}h away; outside the {args.deadline_window_hours}h window. Skipping.")
            return

    fixtures = get_fixtures(event=next_gw["id"])

    snapshot = get_entry_snapshot(args.team_id, data["events"])
    if snapshot is None:
        print(f"Could not fetch squad/finances for team {args.team_id}. Squad may not be locked in yet for this gameweek.")
        return

    free_transfers = args.free_transfers
    if free_transfers is None:
        history = get_entry_history(args.team_id)
        free_transfers = compute_free_transfers(history)
        print(f"Auto-computed free transfers: {free_transfers} (pass --free-transfers to override)")

    bank = snapshot["entry_history"]["bank"]
    full_pool = build_player_pool(data, fixtures)
    pool_by_id = {p["id"]: p for p in full_pool}
    squad = build_squad(pool_by_id, snapshot["picks"])

    suggestions, remaining_bank = suggest_transfers(squad, full_pool, bank, free_transfers, args.max_suggestions)

    print(f"Gameweek {next_gw['id']} — {next_gw['name']}")
    print(f"Bank: £{bank / 10:.1f}m | Free transfers: {free_transfers}\n")

    if not suggestions:
        print("No transfer is worth making this week — your squad's next-GW xP beats the available upgrades.")
        return

    print(f"Suggested transfers ({len(suggestions)}):\n")
    for c in suggestions:
        print(format_transfer(c))
        print()

    total_net = sum(c["net_gain"] for c in suggestions)
    print(f"Total net xP gain: {total_net:+.2f}")
    print(f"Bank after transfers: £{remaining_bank / 10:.1f}m")

    logged = log_suggestions(next_gw["id"], suggestions)
    if not logged:
        print(f"\nAlready suggested transfers for GW{next_gw['id']}; skipping duplicate log/notification.")
        return

    if args.notify:
        lines = [f"GW{next_gw['id']} — Bank £{bank / 10:.1f}m, {free_transfers} FT\n"]
        for c in suggestions:
            lines.append(f"{c['out']['name']} -> {c['in']['name']} ({c['net_gain']:+.2f}{' hit' if c['hit'] else ''})")
        lines.append(f"\nTotal net xP: {total_net:+.2f}")
        message = "\n".join(lines)
        if send_ntfy(message, title=f"FPL GW{next_gw['id']} Transfer Suggestions"):
            print("Notification sent.")


if __name__ == "__main__":
    main()
