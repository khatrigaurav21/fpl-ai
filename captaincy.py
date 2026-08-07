def rank_candidates(players_with_xp: list[dict], top_n: int = 10) -> list[dict]:
    return sorted(players_with_xp, key=lambda p: p["xp"], reverse=True)[:top_n]


def pick_captain_vice(ranked: list[dict], min_minutes_prob: float = 0.75):
    captain = ranked[0]
    vice = next(
        (p for p in ranked[1:] if p["minutes_probability"] >= min_minutes_prob),
        ranked[1],
    )
    return captain, vice
