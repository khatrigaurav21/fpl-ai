import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fpl_client import get_bootstrap_static
from notify import send_ntfy

MIN_OWNERSHIP_FOR_SIGNAL = 0.1  # avoids dividing by ~0 for barely-owned players


def compute_momentum(elements: list[dict], teams: dict[int, str]) -> list[dict]:
    """Heuristic price-change signal from free data only. FPL's real algorithm
    is undisclosed, so this approximates it the way third-party trackers do:
    net transfers this event, scaled by how many managers already own the
    player (a big raw transfer count matters less for a player 50% of the
    league already owns than for one at 2%)."""
    scored = []
    for p in elements:
        if p["status"] == "u":
            continue
        net = p["transfers_in_event"] - p["transfers_out_event"]
        if net == 0:
            continue
        ownership = max(float(p["selected_by_percent"]), MIN_OWNERSHIP_FOR_SIGNAL)
        scored.append(
            {
                "name": f"{p['first_name']} {p['second_name']}",
                "team": teams[p["team"]],
                "price": p["now_cost"] / 10,
                "ownership": float(p["selected_by_percent"]),
                "net_transfers": net,
                "momentum": net / ownership,
            }
        )
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Heuristic price-change momentum tracker (approximation, not FPL's real algorithm).")
    parser.add_argument("--top-n", type=int, default=5, help="How many risers/fallers to show.")
    parser.add_argument("--notify", action="store_true", help="Send a push notification via ntfy.sh (requires NTFY_TOPIC env var).")
    args = parser.parse_args()

    data = get_bootstrap_static()
    teams = {t["id"]: t["name"] for t in data["teams"]}
    scored = compute_momentum(data["elements"], teams)

    if not scored:
        print("No transfer activity yet this gameweek -- nothing to signal on.")
        return

    risers = sorted(scored, key=lambda p: p["momentum"], reverse=True)[: args.top_n]
    fallers = sorted(scored, key=lambda p: p["momentum"])[: args.top_n]

    print("Likely price RISES (heuristic, not official):")
    for p in risers:
        print(f"  {p['name']:<25} {p['team']:<15} £{p['price']:.1f}m  net={p['net_transfers']:+,}  own={p['ownership']}%")

    print("\nLikely price FALLS (heuristic, not official):")
    for p in fallers:
        print(f"  {p['name']:<25} {p['team']:<15} £{p['price']:.1f}m  net={p['net_transfers']:+,}  own={p['ownership']}%")

    if args.notify:
        lines = [
            "RISES: " + ", ".join(f"{p['name']} ({p['net_transfers']:+,})" for p in risers),
            "FALLS: " + ", ".join(f"{p['name']} ({p['net_transfers']:+,})" for p in fallers),
        ]
        message = "\n".join(lines)
        if send_ntfy(message, title="FPL Price Change Watch"):
            print("\nNotification sent.")


if __name__ == "__main__":
    main()
