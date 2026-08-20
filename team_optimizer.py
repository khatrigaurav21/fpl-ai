import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pulp

from fpl_client import build_player_pool, get_bootstrap_static, get_fixtures, get_next_event
from notify import send_ntfy

DEFAULT_BUDGET = 1000  # £100.0m, in tenths
SQUAD_REQUIREMENTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION_LIMITS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
MAX_PER_CLUB = 3
MIN_MINUTES_PROBABILITY = 0.75


def optimize_team(pool: list[dict], budget: int = DEFAULT_BUDGET) -> dict:
    """Picks the single best-scoring valid 15-man squad (and its best starting
    XI + captain) for the next gameweek only, under budget/position/club-limit
    constraints. Solved exactly via MILP rather than approximated greedily,
    since budget forces real tradeoffs across positions that a greedy pick
    would get wrong."""

    eligible = [p for p in pool if p["minutes_probability"] >= MIN_MINUTES_PROBABILITY]
    by_id = {p["id"]: p for p in eligible}

    prob = pulp.LpProblem("fpl_team_optimizer", pulp.LpMaximize)

    squad_vars = {pid: pulp.LpVariable(f"squad_{pid}", cat="Binary") for pid in by_id}
    start_vars = {pid: pulp.LpVariable(f"start_{pid}", cat="Binary") for pid in by_id}
    captain_vars = {pid: pulp.LpVariable(f"cap_{pid}", cat="Binary") for pid in by_id}

    # Starting XI points, plus the extra points a captain's multiplier adds.
    prob += pulp.lpSum(
        by_id[pid]["xp"] * start_vars[pid] + by_id[pid]["xp"] * captain_vars[pid] for pid in by_id
    )

    prob += pulp.lpSum(by_id[pid]["now_cost"] * squad_vars[pid] for pid in by_id) <= budget

    for pos, count in SQUAD_REQUIREMENTS.items():
        prob += pulp.lpSum(squad_vars[pid] for pid in by_id if by_id[pid]["position"] == pos) == count

    for club in {p["team"] for p in eligible}:
        prob += pulp.lpSum(squad_vars[pid] for pid in by_id if by_id[pid]["team"] == club) <= MAX_PER_CLUB

    prob += pulp.lpSum(start_vars.values()) == 11
    for pos, (lo, hi) in FORMATION_LIMITS.items():
        pos_starters = pulp.lpSum(start_vars[pid] for pid in by_id if by_id[pid]["position"] == pos)
        prob += pos_starters >= lo
        prob += pos_starters <= hi

    for pid in by_id:
        prob += start_vars[pid] <= squad_vars[pid]
        prob += captain_vars[pid] <= start_vars[pid]
    prob += pulp.lpSum(captain_vars.values()) == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"Optimizer did not find an optimal solution (status: {pulp.LpStatus[prob.status]}).")

    squad = [by_id[pid] for pid in by_id if squad_vars[pid].value() == 1]
    starters = [by_id[pid] for pid in by_id if start_vars[pid].value() == 1]
    bench = [p for p in squad if p not in starters]
    captain = next(by_id[pid] for pid in by_id if captain_vars[pid].value() == 1)

    return {
        "squad": squad,
        "starters": starters,
        "bench": bench,
        "captain": captain,
        "total_cost": sum(p["now_cost"] for p in squad),
        "starting_xp": round(sum(p["xp"] for p in starters) + captain["xp"], 2),
    }


def pick_best_xi(squad: list[dict]) -> dict:
    """Given an already-fixed 15-man squad (this gameweek's xP already baked
    into each player dict), picks the best valid starting XI + captain for
    that gameweek. No budget/squad-selection constraints -- squad is fixed --
    so this is a much smaller MILP than optimize_team, reused for the Team
    Planner's per-gameweek view of an unchanged squad."""
    by_id = {p["id"]: p for p in squad}

    prob = pulp.LpProblem("fpl_best_xi", pulp.LpMaximize)
    start_vars = {pid: pulp.LpVariable(f"start_{pid}", cat="Binary") for pid in by_id}
    captain_vars = {pid: pulp.LpVariable(f"cap_{pid}", cat="Binary") for pid in by_id}

    prob += pulp.lpSum(
        by_id[pid]["xp"] * start_vars[pid] + by_id[pid]["xp"] * captain_vars[pid] for pid in by_id
    )

    prob += pulp.lpSum(start_vars.values()) == 11
    for pos, (lo, hi) in FORMATION_LIMITS.items():
        pos_starters = pulp.lpSum(start_vars[pid] for pid in by_id if by_id[pid]["position"] == pos)
        prob += pos_starters >= lo
        prob += pos_starters <= hi

    for pid in by_id:
        prob += captain_vars[pid] <= start_vars[pid]
    prob += pulp.lpSum(captain_vars.values()) == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"pick_best_xi did not find an optimal solution (status: {pulp.LpStatus[prob.status]}).")

    starters = [by_id[pid] for pid in by_id if start_vars[pid].value() == 1]
    bench = [p for p in squad if p["id"] not in {s["id"] for s in starters}]
    captain = next(by_id[pid] for pid in by_id if captain_vars[pid].value() == 1)
    vice = max((p for p in starters if p["id"] != captain["id"]), key=lambda p: p["xp"])

    return {
        "starters": starters,
        "bench": bench,
        "captain": captain,
        "vice": vice,
        "total_points": round(sum(p["xp"] for p in starters) + captain["xp"], 2),
    }


def format_team(result: dict) -> str:
    lines = []
    for pos in ("GKP", "DEF", "MID", "FWD"):
        starters = [p for p in result["starters"] if p["position"] == pos]
        if not starters:
            continue
        lines.append(pos)
        for p in sorted(starters, key=lambda p: p["xp"], reverse=True):
            tag = " (C)" if p["id"] == result["captain"]["id"] else ""
            lines.append(f"  {p['name']:<25} {p['team']:<15} £{p['now_cost'] / 10:.1f}m  xP={p['xp']:.2f}{tag}")
        lines.append("")

    lines.append("Bench")
    for p in sorted(result["bench"], key=lambda p: p["xp"], reverse=True):
        lines.append(f"  {p['name']:<25} {p['team']:<15} £{p['now_cost'] / 10:.1f}m  xP={p['xp']:.2f}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimal budget-constrained squad for the next gameweek.")
    parser.add_argument("--budget", type=float, default=100.0, help="Total budget in £m (default 100.0).")
    parser.add_argument("--notify", action="store_true", help="Send a push notification via ntfy.sh (requires NTFY_TOPIC env var).")
    args = parser.parse_args()

    data = get_bootstrap_static()
    next_gw = get_next_event(data["events"])
    fixtures = get_fixtures(event=next_gw["id"])
    pool = build_player_pool(data, fixtures)

    result = optimize_team(pool, budget=round(args.budget * 10))

    print(f"Gameweek {next_gw['id']} — {next_gw['name']}")
    print(f"Squad cost: £{result['total_cost'] / 10:.1f}m / £{args.budget:.1f}m budget\n")
    print(format_team(result))
    print(f"\nCaptain: {result['captain']['name']} (xP={result['captain']['xp']})")
    print(f"Projected starting XI points (with captaincy): {result['starting_xp']}")

    if args.notify:
        starter_lines = [f"{p['name']} ({p['xp']})" for p in sorted(result["starters"], key=lambda p: p["xp"], reverse=True)]
        message = (
            f"Captain: {result['captain']['name']}\n"
            f"Projected points: {result['starting_xp']}\n"
            f"Cost: £{result['total_cost'] / 10:.1f}m\n\n" + "\n".join(starter_lines)
        )
        if send_ntfy(message, title=f"FPL GW{next_gw['id']} Optimal Team"):
            print("Notification sent.")


if __name__ == "__main__":
    main()
