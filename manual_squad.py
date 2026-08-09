import json


def _build_name_index(full_pool: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for p in full_pool:
        index.setdefault(p["web_name"].lower(), []).append(p)
        index.setdefault(p["name"].lower(), []).append(p)
    return index


def _resolve(raw_name: str, full_pool: list[dict], index: dict[str, list[dict]]) -> dict:
    key = raw_name.strip().lower()
    matches = index.get(key)

    if not matches:
        matches = [p for p in full_pool if key in p["web_name"].lower() or key in p["name"].lower()]

    unique = {p["id"]: p for p in matches}
    if not unique:
        raise ValueError(f"No player found matching '{raw_name}'. Check spelling against the FPL site.")
    if len(unique) > 1:
        options = ", ".join(f"{p['web_name']} ({p['team']})" for p in list(unique.values())[:6])
        raise ValueError(f"'{raw_name}' is ambiguous, matches: {options}. Use a more specific name.")
    return next(iter(unique.values()))


def resolve_players(names: list[str], full_pool: list[dict]) -> list[dict]:
    """Matches a list of player names (web_name, full name, or unambiguous
    substring) against the live player pool. selling_price is approximated as
    now_cost since real sell price only diverges after price rises -- fine
    right after a squad is first set, less accurate later in the season."""
    index = _build_name_index(full_pool)
    squad = []
    seen_ids = set()
    for raw_name in names:
        player = dict(_resolve(raw_name, full_pool, index))
        if player["id"] in seen_ids:
            raise ValueError(f"Duplicate player in squad: {raw_name}")
        seen_ids.add(player["id"])
        player["selling_price"] = player["now_cost"]
        squad.append(player)

    if len(squad) != 15:
        raise ValueError(f"Squad must list exactly 15 players (got {len(squad)}).")

    return squad


def load_manual_squad(path: str, full_pool: list[dict]) -> tuple[list[dict], int]:
    """Loads a squad from a JSON file ({"bank": <tenths of £1m>, "players": [names...]})
    for use before the FPL API exposes real picks (i.e. before the gameweek deadline
    passes)."""
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    return resolve_players(config["players"], full_pool), config["bank"]
