# FPL AI

A points-maximizer for Fantasy Premier League — and a testbed for learning RAG and other applied-AI techniques on a real, personally-useful problem.

## Status

Core loop is built and running on a daily schedule. Still in the validation window — nothing here should be trusted blindly until the 4-gameweek check described below actually runs its course.

## Web app

`server.py` (FastAPI) + `web/` (vanilla HTML/CSS/JS, no build step) is the primary interface — one app, one URL, every tool below as a tab: Captain Pick, Transfers, Team Optimizer, Price Tracker, Horizon Planner (clearly marked experimental in the UI itself, not just here), and the AI chat assistant.

```bash
uvicorn server:app --reload
```

Then open http://127.0.0.1:8000. Each tab is a thin wrapper over the same underlying modules described below — no logic was duplicated or reimplemented for the web app, so anything already true about a feature's validation status is still true here.

The daily automated captain-pick/transfer-suggestion job stays a separate GitHub Actions workflow, since it runs unattended on a schedule — nothing to click there.

## Deployment

The web app is deployable as-is (nothing to rewrite) to any host that can build from a GitHub repo and run a Python web service — e.g. Render, Railway, or Fly.io. Using Render as the concrete example:

1. **render.com → New → Web Service → connect the `fpl-ai` GitHub repo.**
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT` (also in `Procfile`, which some platforms auto-detect)
4. Environment variables (Render dashboard → Environment):
   - `GEMINI_API_KEY` — same key as local dev
   - `APP_PASSWORD` — gates the whole app behind HTTP Basic Auth (any username, this password) so a public URL can't be found and used by a stranger, burning your Gemini quota. Unset locally, the app runs gate-free; set it only on the public deployment.
5. Deploy. Render auto-redeploys on every push to `master`.

Render's free tier sleeps after 15 minutes idle (first request after that takes ~30s to wake back up) — fine for occasional personal use; upgrade to a paid tier if you want zero cold-start delay.

## What it does

All free data — the unauthenticated FPL API only, no scraping, no paid feeds. Every piece below is also usable standalone from the command line, if you don't want the web app.

- **`main.py`** — expected points per player for the next gameweek (`form × fixture-difficulty × probability-of-playing`), a captaincy + vice pick, and a top-3-per-position breakdown. Logs every run to `predictions_log.csv` for accuracy tracking.
- **`transfers.py`** — budget-aware transfer suggestions (up to 3), respecting your bank, the 3-per-club limit, and squad composition. Free transfers are auto-computed from your transfer history; hits are only suggested when a specific swap's own xP gain outweighs the -4.
- **`team_optimizer.py`** — the single best possible 15-man squad under a budget, solved exactly via MILP (PuLP/CBC), including the optimal captain choice as part of the objective, not picked after the fact.
- **`price_tracker.py`** — heuristic price-change momentum (net transfers scaled by ownership), since FPL's real algorithm is undisclosed.
- **`chat.py`** / **`chat_ui.py`** — a small RAG assistant: ask natural-language questions and get answers grounded in this project's own computed data (not general football knowledge). Keyword-based retrieval for now; real embeddings are the natural next step. Uses Gemini (free tier) — requires your own `GEMINI_API_KEY` from aistudio.google.com/apikey. `chat.py` is the CLI; `chat_ui.py` runs the same thing as a real chat interface in your browser (Gradio).
- **GitHub Actions** (`.github/workflows/captain-pick.yml`) — runs the captain pick and transfer suggester daily, only acting within 36 hours of a deadline, pushing results to your phone via ntfy.
- **`youtube_source.py`** — checks configured FPL YouTube creators (FPL Harry, FPL Raptor, FPL Mate, Let's Talk FPL) for new uploads, fetches the transcript, chunks it, and feeds it into the same knowledge base the chat assistant reads from — so you can ask "what does X think about Y" grounded in what they actually said. Requires your own `YOUTUBE_API_KEY` (free, Google Cloud Console). Dedupes per-video via `video_sources_log.csv`; caches resolved channel IDs in `youtube_channels_cache.json` so the (quota-limited) channel-lookup call only happens once per channel. **Manual/local-only, not in the daily automation** — GitHub Actions runners sit on cloud-provider IPs that YouTube's transcript endpoint blocks categorically (confirmed via a real run: channel/video lookup worked, transcript fetch failed every time with an IP-block error). Run it yourself from your own machine when you want fresh content.
- **`horizon_planner.py`** — ⚠️ **EXPERIMENTAL, unvalidated.** A real joint multi-period MILP: squad/transfer/captain decisions across a 3-5 week horizon simultaneously, with free-transfer banking (capped at 5, resets correctly after a hit week) and a heuristic confidence-decay on further-out weeks. The MILP formulation itself is rigorously tested (isolated unit tests on the free-transfer linearization, full constraint verification against live data). What's *not* validated is the thing it's built on: the single-gameweek xP model has never been checked against a real result. This compounds that unvalidated model across weeks on purpose, as a technical exercise — not a plan to actually follow yet. See the module docstring before using it for real decisions.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate  # or .venv/bin/activate on Linux/Mac
pip install -r requirements.txt
```

For `chat.py`, copy `.env.example` to `.env` and add your own free key from aistudio.google.com/apikey.

## Usage

```bash
python main.py --team-id <your-id>              # captain pick + top picks by position
python transfers.py --team-id <your-id>          # transfer suggestions
python team_optimizer.py                          # optimal squad from scratch, any budget
python price_tracker.py                           # price-change momentum
python chat.py "who should I captain this week"   # ask anything (CLI)
python chat_ui.py                                 # same thing, in a browser chat UI
python horizon_planner.py --horizon 3             # EXPERIMENTAL multi-week plan, not validated
python youtube_source.py                          # check configured channels for new uploads
```

Your team ID is the number in the URL when you view your team on the FPL site (`.../entry/<id>/...`).

**Before your gameweek deadline passes, the FPL API won't return your picks.** Use `--squad-file squad.json` instead (see `squad.example.json` for the format) as a manual override — `squad.json` itself is gitignored since it's your personal data.

Fill in `actual_captain_points` in `predictions_log.csv` after each gameweek — that comparison is the whole point of the validation phase.

## Roadmap

Built: captaincy engine, transfer-hit calculator, squad optimizer, price tracker, RAG chat assistant, daily automation, multi-GW horizon planner (experimental), YouTube creator transcript ingestion.

The horizon planner was originally deferred for a specific reason — front-loading a multi-week optimizer before the underlying weekly forecast is validated risks compounding an unproven model's errors across time — and was built anyway as a deliberate technical exercise, clearly labeled as unvalidated rather than pretending the underlying risk went away. The plan is to keep it experimental until the 4-gameweek validation check below actually gives the single-week model a track record to build on.

Still deferred, on purpose:
- **Chip-timing solver** — a lightweight fixture-swing lookup covers most of the value without a full optimizer.
- **Effective ownership / Elite XI tracking** — real data-engineering scope (polling many public mini-league entries), not a quick add.
- **Opta-grade stats** (DEFCON, advanced xG) — would require a paid data license; free-only has been the rule so far and there's no case yet for breaking it.

The rule that's held throughout: nothing gets promoted from this list without a specific case for why the free/simple version isn't enough.
