POSITION_ORDER = ("GKP", "DEF", "MID", "FWD")


def rank_candidates(players_with_xp: list[dict], top_n: int = 10) -> list[dict]:
    return sorted(players_with_xp, key=lambda p: p["xp"], reverse=True)[:top_n]


def top_by_position(players_with_xp: list[dict], n: int = 3) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for p in players_with_xp:
        grouped.setdefault(p["position"], []).append(p)
    return {
        pos: sorted(grouped[pos], key=lambda p: p["xp"], reverse=True)[:n]
        for pos in POSITION_ORDER
        if pos in grouped
    }


def pick_captain_vice(ranked: list[dict], min_minutes_prob: float = 0.75):
    captain = ranked[0]
    vice = next(
        (p for p in ranked[1:] if p["minutes_probability"] >= min_minutes_prob),
        ranked[1],
    )
    return captain, vice
