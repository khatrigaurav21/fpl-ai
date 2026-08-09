"""
EXPERIMENTAL. Multi-gameweek transfer planner.

This is explicitly NOT validated the way the rest of this project is. The
single-gameweek xP model this is built on has never been checked against a
real result (still preseason as of writing), and this planner compounds that
unvalidated model across several weeks with a heuristic confidence-decay
factor -- there is no real uncertainty quantification behind that decay, it's
a guess. Treat this as a technical exercise in multi-period MILP formulation,
not a transfer plan to actually trust yet. See README for the reasoning
behind why this was deferred, and why it's being built anyway.
"""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pulp

from fpl_client import build_player_pool, get_bootstrap_static, get_entry_history, get_entry_snapshot, get_fixtures, get_next_event
from manual_squad import load_manual_squad
from team_optimizer import FORMATION_LIMITS, MAX_PER_CLUB, MIN_MINUTES_PROBABILITY, SQUAD_REQUIREMENTS
from transfers import build_squad, compute_free_transfers

HIT_COST = 4
MAX_BANKED_TRANSFERS = 5
DECAY_PER_WEEK = 0.95  # heuristic only -- see module docstring
BIG_M = 20  # safely above any plausible weekly transfer count
# Must equal SQUAD size exactly, not "a big number". Building a 15-man squad
# from empty always uses exactly 15 transfer_in actions in this model, so
# banked[0] = max(0, this - 15). Set any higher and banked[0] becomes
# positive, incorrectly carrying leftover "unlimited" transfers into GW2's
# free-transfer count (verified: 16 -> wrongly gives 2 FT, 100 -> wrongly
# gives 5 FT). Real FPL always starts GW2 at exactly 1 FT regardless of how
# the preseason squad was built -- this constant being exactly 15 is what
# reproduces that, not a coincidence to "round up" later.
UNLIMITED_STARTING_TRANSFERS = 15


def build_horizon_pools(data: dict, start_gw_id: int, horizon: int) -> dict[int, dict[int, dict]]:
    """{gw_id: {player_id: player_dict}} for each week in the horizon, with xP
    decayed further out as a rough stand-in for genuinely wider uncertainty."""
    pools = {}
    for i in range(horizon):
        gw_id = start_gw_id + i
        fixtures = get_fixtures(event=gw_id)
        pool = build_player_pool(data, fixtures)
        decay = DECAY_PER_WEEK**i
        for p in pool:
            p["xp"] = round(p["xp"] * decay, 3)
        pools[gw_id] = {p["id"]: p for p in pool}
    return pools


def optimize_horizon(
    pools: dict[int, dict[int, dict]],
    gw_ids: list[int],
    initial_squad_ids: set[int],
    initial_bank: int,
    initial_free_transfers: int,
) -> dict:
    T = len(gw_ids)

    all_ids = set()
    for pool in pools.values():
        all_ids |= set(pool.keys())
    eligible_ids = [
        pid
        for pid in all_ids
        if all(pid in pools[gw] and pools[gw][pid]["minutes_probability"] >= MIN_MINUTES_PROBABILITY for gw in gw_ids)
    ]

    prob = pulp.LpProblem("fpl_horizon_planner", pulp.LpMaximize)

    squad = {(pid, t): pulp.LpVariable(f"squad_{pid}_{t}", cat="Binary") for pid in eligible_ids for t in range(T)}
    start = {(pid, t): pulp.LpVariable(f"start_{pid}_{t}", cat="Binary") for pid in eligible_ids for t in range(T)}
    captain = {(pid, t): pulp.LpVariable(f"cap_{pid}_{t}", cat="Binary") for pid in eligible_ids for t in range(T)}
    transfer_in = {(pid, t): pulp.LpVariable(f"in_{pid}_{t}", cat="Binary") for pid in eligible_ids for t in range(T)}
    transfer_out = {(pid, t): pulp.LpVariable(f"out_{pid}_{t}", cat="Binary") for pid in eligible_ids for t in range(T)}

    bank = [pulp.LpVariable(f"bank_{t}", lowBound=0, cat="Integer") for t in range(T)]
    hits = [pulp.LpVariable(f"hits_{t}", lowBound=0, cat="Integer") for t in range(T)]
    banked = [pulp.LpVariable(f"banked_{t}", lowBound=0, upBound=MAX_BANKED_TRANSFERS, cat="Integer") for t in range(T)]
    hit_flag = [pulp.LpVariable(f"hitflag_{t}", cat="Binary") for t in range(T)]
    # ft_start[t]: free transfers available at the START of week t, before that
    # week's transfers. Index 0 is a fixed constant (given), not a variable.
    ft_start = [initial_free_transfers] + [
        pulp.LpVariable(f"ft_start_{t}", lowBound=0, upBound=MAX_BANKED_TRANSFERS, cat="Integer") for t in range(1, T)
    ]

    prob += pulp.lpSum(
        pools[gw_ids[t]][pid]["xp"] * start[pid, t] + pools[gw_ids[t]][pid]["xp"] * captain[pid, t]
        for pid in eligible_ids
        for t in range(T)
    ) - HIT_COST * pulp.lpSum(hits)

    for t in range(T):
        gw = gw_ids[t]

        for pos, count in SQUAD_REQUIREMENTS.items():
            prob += pulp.lpSum(squad[pid, t] for pid in eligible_ids if pools[gw][pid]["position"] == pos) == count
        for club in {pools[gw][pid]["team"] for pid in eligible_ids}:
            prob += pulp.lpSum(squad[pid, t] for pid in eligible_ids if pools[gw][pid]["team"] == club) <= MAX_PER_CLUB

        prob += pulp.lpSum(start[pid, t] for pid in eligible_ids) == 11
        for pos, (lo, hi) in FORMATION_LIMITS.items():
            pos_starters = pulp.lpSum(start[pid, t] for pid in eligible_ids if pools[gw][pid]["position"] == pos)
            prob += pos_starters >= lo
            prob += pos_starters <= hi
        prob += pulp.lpSum(captain[pid, t] for pid in eligible_ids) == 1

        for pid in eligible_ids:
            prob += start[pid, t] <= squad[pid, t]
            prob += captain[pid, t] <= start[pid, t]

            prev_squad = squad[pid, t - 1] if t > 0 else int(pid in initial_squad_ids)
            prob += squad[pid, t] == prev_squad + transfer_in[pid, t] - transfer_out[pid, t]
            prob += transfer_out[pid, t] <= prev_squad
            prob += transfer_in[pid, t] <= 1 - prev_squad

        transfers_made = pulp.lpSum(transfer_in[pid, t] for pid in eligible_ids)

        sell_value = pulp.lpSum(pools[gw][pid]["now_cost"] * transfer_out[pid, t] for pid in eligible_ids)
        buy_cost = pulp.lpSum(pools[gw][pid]["now_cost"] * transfer_in[pid, t] for pid in eligible_ids)
        prev_bank = bank[t - 1] if t > 0 else initial_bank
        prob += bank[t] == prev_bank + sell_value - buy_cost

        # hits[t] = max(0, transfers_made - ft_start[t]); solver naturally
        # tightens this to the true value since extra hits only hurt the objective.
        prob += hits[t] >= transfers_made - ft_start[t]
        prob += hits[t] >= 0

        # hit_flag[t] = 1 whenever a hit is actually needed this week.
        prob += transfers_made - ft_start[t] <= BIG_M * hit_flag[t]

        # banked[t] = max(0, ft_start[t] - transfers_made); solver pushes this
        # up since more banked is always beneficial for future weeks, so the
        # hit_flag linking constraint alone (no second direction needed) is
        # enough to make this bind correctly at optimality.
        prob += banked[t] <= ft_start[t] - transfers_made + BIG_M * hit_flag[t]
        prob += banked[t] <= BIG_M * (1 - hit_flag[t])

        if t + 1 < T:
            prob += ft_start[t + 1] <= banked[t] + 1
            prob += ft_start[t + 1] <= MAX_BANKED_TRANSFERS

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"Horizon planner did not find an optimal solution (status: {pulp.LpStatus[prob.status]}).")

    weeks = []
    for t in range(T):
        gw = gw_ids[t]
        week_squad = [pools[gw][pid] for pid in eligible_ids if squad[pid, t].value() == 1]
        week_starters = [pools[gw][pid] for pid in eligible_ids if start[pid, t].value() == 1]
        week_captain = next(pools[gw][pid] for pid in eligible_ids if captain[pid, t].value() == 1)
        transfers_in_week = [pools[gw][pid] for pid in eligible_ids if transfer_in[pid, t].value() == 1]
        transfers_out_week = [pools[gw][pid] for pid in eligible_ids if transfer_out[pid, t].value() == 1]
        weeks.append(
            {
                "gw": gw,
                "squad": week_squad,
                "starters": week_starters,
                "captain": week_captain,
                "transfers_in": transfers_in_week,
                "transfers_out": transfers_out_week,
                "hits": int(round(hits[t].value())),
                "free_transfers_available": int(round(ft_start[t])) if t == 0 else int(round(ft_start[t].value())),
                "bank": int(round(bank[t].value())),
                "points": round(sum(p["xp"] for p in week_starters) + week_captain["xp"], 2),
            }
        )
    return {"weeks": weeks, "total_points": round(sum(w["points"] - w["hits"] * HIT_COST for w in weeks), 2)}


def format_plan(result: dict) -> str:
    lines = []
    for w in result["weeks"]:
        lines.append(f"GW{w['gw']} -- free transfers available: {w['free_transfers_available']}, bank: £{w['bank'] / 10:.1f}m")
        if w["transfers_in"]:
            for out_p, in_p in zip(w["transfers_out"], w["transfers_in"]):
                lines.append(f"  Transfer: {out_p['name']} -> {in_p['name']}")
        else:
            lines.append("  No transfers")
        if w["hits"]:
            lines.append(f"  Hits taken: {w['hits']} (-{w['hits'] * HIT_COST} pts)")
        lines.append(f"  Captain: {w['captain']['name']} (xP={w['captain']['xp']:.2f})")
        lines.append(f"  Projected points (starters + captain bonus, before hits): {w['points']:.2f}")
        lines.append("")
    lines.append(f"Total projected points across horizon (net of hits): {result['total_points']:.2f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="EXPERIMENTAL multi-gameweek transfer planner. Not validated -- see module docstring.")
    parser.add_argument("--team-id", type=int, default=None, help="Your FPL team/entry ID.")
    parser.add_argument("--squad-file", type=str, default=None, help="Manual squad JSON file, used instead of --team-id.")
    parser.add_argument("--free-transfers", type=int, default=None, help="Starting free transfers. Auto-computed from history if --team-id is given.")
    parser.add_argument("--bank", type=float, default=None, help="Starting bank in £m. Defaults to full budget if no squad is given.")
    parser.add_argument("--horizon", type=int, default=3, help="Number of gameweeks to plan across (max 5).")
    args = parser.parse_args()

    if args.horizon < 1 or args.horizon > 5:
        parser.error("--horizon must be between 1 and 5.")

    print("EXPERIMENTAL feature -- not validated. See horizon_planner.py's module docstring before trusting this output.\n")

    data = get_bootstrap_static()
    next_gw = get_next_event(data["events"])
    pools = build_horizon_pools(data, next_gw["id"], args.horizon)
    gw_ids = list(pools.keys())

    if args.squad_file:
        full_pool_for_matching = build_player_pool(data, get_fixtures(event=next_gw["id"]))
        squad, bank = load_manual_squad(args.squad_file, full_pool_for_matching)
        initial_squad_ids = {p["id"] for p in squad}
        initial_bank = round(bank * 10) if isinstance(bank, float) else bank
    elif args.team_id:
        snapshot = get_entry_snapshot(args.team_id, data["events"])
        if snapshot is None:
            print(f"Could not fetch squad for team {args.team_id}. Try --squad-file instead.")
            return
        initial_squad_ids = {p["element"] for p in snapshot["picks"]}
        initial_bank = snapshot["entry_history"]["bank"]
    else:
        print("No squad given -- planning from an empty squad (preseason-style unlimited initial picks).\n")
        initial_squad_ids = set()
        initial_bank = round(args.bank * 10) if args.bank is not None else 1000

    if args.free_transfers is not None:
        initial_free_transfers = args.free_transfers
    elif args.team_id:
        initial_free_transfers = compute_free_transfers(get_entry_history(args.team_id))
    elif not initial_squad_ids:
        initial_free_transfers = UNLIMITED_STARTING_TRANSFERS
    else:
        parser.error("--free-transfers is required when using --squad-file without --team-id.")

    result = optimize_horizon(pools, gw_ids, initial_squad_ids, initial_bank, initial_free_transfers)
    print(format_plan(result))


if __name__ == "__main__":
    main()
