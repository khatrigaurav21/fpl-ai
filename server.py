import base64
import os
import secrets
import time

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from captaincy import pick_captain_vice, rank_candidates, top_by_position
from chat import DEFAULT_MODEL, ask
from fpl_client import build_player_pool, get_bootstrap_static, get_entry_history, get_entry_snapshot, get_fixtures, get_next_event
from horizon_planner import UNLIMITED_STARTING_TRANSFERS, build_horizon_pools, optimize_horizon
from knowledge_base import build_knowledge_base
from manual_squad import resolve_players
from price_tracker import compute_momentum
from team_optimizer import optimize_team
from transfers import build_squad, compute_free_transfers, suggest_transfers

class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gates every request (API and static files) behind HTTP Basic Auth when
    APP_PASSWORD is set. Username is ignored -- it's a single shared password,
    not per-user accounts. If APP_PASSWORD isn't set (e.g. local dev), the
    gate is skipped entirely so nothing changes for `uvicorn server:app`
    without the env var."""

    async def dispatch(self, request, call_next):
        password = os.environ.get("APP_PASSWORD")
        if not password:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _, _, provided = decoded.partition(":")
                if secrets.compare_digest(provided, password):
                    return await call_next(request)
            except Exception:
                pass

        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="FPL AI"'})


app = FastAPI(title="FPL AI")
app.add_middleware(BasicAuthMiddleware)

CACHE_TTL = 300
_gw_cache = {"data": None, "fixtures": None, "next_gw": None, "fetched_at": 0.0}
_kb_cache = {"docs": None, "gw": None, "fetched_at": 0.0}
_chat_client = None


def get_gw_data():
    now = time.time()
    if _gw_cache["data"] is None or now - _gw_cache["fetched_at"] > CACHE_TTL:
        data = get_bootstrap_static()
        next_gw = get_next_event(data["events"])
        fixtures = get_fixtures(event=next_gw["id"])
        _gw_cache.update(data=data, fixtures=fixtures, next_gw=next_gw, fetched_at=now)
    return _gw_cache["data"], _gw_cache["fixtures"], _gw_cache["next_gw"]


class SquadInput(BaseModel):
    team_id: int | None = None
    players: list[str] | None = None
    bank: float | None = None


def resolve_squad(inp: SquadInput, data: dict, fixtures: list[dict]) -> tuple[list[dict] | None, int | None]:
    """Returns (squad_with_prices, bank_in_tenths) or (None, None) if no squad given."""
    if inp.players:
        full_pool = build_player_pool(data, fixtures)
        try:
            squad = resolve_players(inp.players, full_pool)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return squad, round((inp.bank or 0) * 10)

    if inp.team_id:
        snapshot = get_entry_snapshot(inp.team_id, data["events"])
        if snapshot is None:
            raise HTTPException(400, "Could not fetch squad for that team ID (not locked yet?). Try entering players manually.")
        full_pool = build_player_pool(data, fixtures)
        pool_by_id = {p["id"]: p for p in full_pool}
        squad = build_squad(pool_by_id, snapshot["picks"])
        return squad, snapshot["entry_history"]["bank"]

    return None, None


@app.get("/api/gw")
def api_gw():
    _, _, next_gw = get_gw_data()
    return {"gw": next_gw["id"], "name": next_gw["name"], "deadline": next_gw["deadline_time"]}


@app.post("/api/captain")
def api_captain(inp: SquadInput):
    data, fixtures, next_gw = get_gw_data()
    squad, _ = resolve_squad(inp, data, fixtures)
    squad_ids = {p["id"] for p in squad} if squad else None

    pool = build_player_pool(data, fixtures, squad_ids)
    if not pool:
        raise HTTPException(400, "No players found for this gameweek.")

    full_ranking = rank_candidates(pool, top_n=len(pool))
    captain, vice = pick_captain_vice(full_ranking)
    by_position = top_by_position(pool, n=5)

    return {"gw": next_gw["id"], "captain": captain, "vice": vice, "by_position": by_position}


class TransferInput(SquadInput):
    free_transfers: int | None = None
    max_suggestions: int = 3


@app.post("/api/transfers")
def api_transfers(inp: TransferInput):
    data, fixtures, next_gw = get_gw_data()
    squad, bank = resolve_squad(inp, data, fixtures)
    if squad is None:
        raise HTTPException(400, "A squad (team ID or player list) is required for transfer suggestions.")
    full_pool = build_player_pool(data, fixtures)

    free_transfers = inp.free_transfers
    if free_transfers is None:
        if inp.team_id:
            free_transfers = compute_free_transfers(get_entry_history(inp.team_id))
        else:
            raise HTTPException(400, "free_transfers is required when using a manual player list.")

    suggestions, remaining_bank = suggest_transfers(squad, full_pool, bank, free_transfers, inp.max_suggestions)
    return {
        "gw": next_gw["id"],
        "bank": bank,
        "free_transfers": free_transfers,
        "suggestions": suggestions,
        "remaining_bank": remaining_bank,
    }


class OptimizeInput(BaseModel):
    budget: float = 100.0


@app.post("/api/optimize")
def api_optimize(inp: OptimizeInput):
    data, fixtures, next_gw = get_gw_data()
    pool = build_player_pool(data, fixtures)
    result = optimize_team(pool, budget=round(inp.budget * 10))
    return {"gw": next_gw["id"], **result}


@app.get("/api/prices")
def api_prices(top_n: int = 5):
    data, _, next_gw = get_gw_data()
    teams = {t["id"]: t["name"] for t in data["teams"]}
    scored = compute_momentum(data["elements"], teams)
    if not scored:
        return {"gw": next_gw["id"], "risers": [], "fallers": [], "message": "No transfer activity yet this gameweek."}
    risers = sorted(scored, key=lambda p: p["momentum"], reverse=True)[:top_n]
    fallers = sorted(scored, key=lambda p: p["momentum"])[:top_n]
    return {"gw": next_gw["id"], "risers": risers, "fallers": fallers}


class HorizonInput(SquadInput):
    free_transfers: int | None = None
    horizon: int = 3


@app.post("/api/horizon")
def api_horizon(inp: HorizonInput):
    if not (1 <= inp.horizon <= 5):
        raise HTTPException(400, "horizon must be between 1 and 5.")

    data, _, next_gw = get_gw_data()
    pools = build_horizon_pools(data, next_gw["id"], inp.horizon)
    gw_ids = list(pools.keys())

    if inp.players or inp.team_id:
        squad, bank = resolve_squad(inp, data, get_fixtures(event=next_gw["id"]))
        initial_squad_ids = {p["id"] for p in squad}
        initial_bank = bank
        free_transfers = inp.free_transfers
        if free_transfers is None:
            if inp.team_id:
                free_transfers = compute_free_transfers(get_entry_history(inp.team_id))
            else:
                raise HTTPException(400, "free_transfers is required when using a manual player list.")
    else:
        initial_squad_ids = set()
        initial_bank = round((inp.bank or 100.0) * 10)
        free_transfers = UNLIMITED_STARTING_TRANSFERS

    result = optimize_horizon(pools, gw_ids, initial_squad_ids, initial_bank, free_transfers)
    return result


def get_chat_client():
    global _chat_client
    if _chat_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(400, "GEMINI_API_KEY is not set on the server. See .env.example.")
        from google import genai

        _chat_client = genai.Client(api_key=api_key)
    return _chat_client


def get_knowledge_base():
    now = time.time()
    if _kb_cache["docs"] is None or now - _kb_cache["fetched_at"] > CACHE_TTL:
        docs, gw = build_knowledge_base()
        _kb_cache.update(docs=docs, gw=gw, fetched_at=now)
    return _kb_cache["docs"], _kb_cache["gw"]


class ChatInput(BaseModel):
    message: str


@app.post("/api/chat")
def api_chat(inp: ChatInput):
    client = get_chat_client()
    docs, gw = get_knowledge_base()
    answer = ask(inp.message, docs, gw, client, DEFAULT_MODEL)
    return {"answer": answer}


# Mounted last so the /api/* routes above take precedence.
app.mount("/", StaticFiles(directory="web", html=True), name="web")
