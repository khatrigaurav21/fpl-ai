# Next-GW expected points: form (or points-per-game fallback) x fixture
# difficulty x probability of playing. Fixture multiplier sums across a
# player's fixtures for the GW, so double gameweeks are handled for free.

FDR_MULTIPLIER = {1: 1.3, 2: 1.15, 3: 1.0, 4: 0.85, 5: 0.7}

STATUS_FALLBACK_PROBABILITY = {"a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0}


def minutes_probability(player: dict) -> float:
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        return chance / 100
    return STATUS_FALLBACK_PROBABILITY.get(player.get("status"), 1.0)


def fixture_multiplier(team_id: int, gw_fixtures: list[dict]) -> float:
    team_fixtures = [
        f for f in gw_fixtures if f["team_h"] == team_id or f["team_a"] == team_id
    ]
    if not team_fixtures:
        return 0.0  # blank gameweek for this team

    total = 0.0
    for f in team_fixtures:
        is_home = f["team_h"] == team_id
        fdr = f["team_h_difficulty"] if is_home else f["team_a_difficulty"]
        total += FDR_MULTIPLIER.get(fdr, 1.0)
    return total


def base_score(player: dict) -> float:
    try:
        form = float(player.get("form") or 0)
        if form > 0:
            return form
    except (TypeError, ValueError):
        pass
    try:
        return float(player.get("points_per_game") or 0)
    except (TypeError, ValueError):
        return 0.0


def expected_points(player: dict, gw_fixtures: list[dict]) -> float:
    return (
        base_score(player)
        * fixture_multiplier(player["team"], gw_fixtures)
        * minutes_probability(player)
    )
