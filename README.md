# FPL AI

A points-maximizer for Fantasy Premier League — and a testbed for learning RAG and other applied-AI techniques on a real, personally-useful problem.

## Status: Phase 1 (validation)

This is deliberately minimal right now. Before adding anything more (multi-gameweek planning, chip timing, RAG over injury news, a web UI), the core expected-points model needs to prove it beats gut-feel over a few live gameweeks. Everything else is on hold until that gate is cleared — see [Roadmap](#roadmap).

## What it does

- Pulls the free, unauthenticated FPL API (`bootstrap-static`, `fixtures`) — no scraping, no paid feeds.
- Scores every player for the next gameweek: `form × fixture-difficulty × probability-of-playing`.
- Ranks candidates and recommends a captain + vice (vice is filtered to players with ≥75% chance of playing, so the safety net actually plays).
- Logs every recommendation to `predictions_log.csv` with an empty `actual_captain_points` column, so results can be checked against reality after each gameweek.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate  # or .venv/bin/activate on Linux/Mac
pip install -r requirements.txt
```

## Usage

```bash
python main.py                        # ranks the full player pool
python main.py --team-id <your-id>    # ranks only your current squad
python main.py --top-n 5              # show fewer/more candidates
```

Your team ID is the number in the URL when you view your team on the FPL site (`.../entry/<id>/...`).

Run it before each gameweek deadline. It appends a row to `predictions_log.csv` — fill in `actual_captain_points` afterward to track whether the model is actually working.

## Roadmap

1. **Validate** — run for 4+ live gameweeks, compare logged predictions against gut-feel and a naive baseline. If it doesn't win, stop and rethink before building anything else.
2. **Transfer-hit calculator** — a small, bounded check ("take -4 now vs. bank") to close a known correctness gap in a purely greedy, single-gameweek model.
3. **Chip-timing heuristic** — a lightweight fixture-swing lookup, not a full solver.
4. **Multi-gameweek planner** — only if the validated single-GW model and the above heuristics turn out not to be enough on their own.
5. **AI/RAG layer** — a natural-language interface over player data, news, and this project's own reasoning, once there's real data underneath it worth querying.

Steps 2–5 are intentionally deferred. Adding infrastructure, scraped data sources, or a full optimizer before step 1 is validated is the specific mistake this roadmap is designed to avoid.
