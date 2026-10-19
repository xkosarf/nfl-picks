"""Web app: login, weekly picks, results."""

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from itertools import groupby
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db, picks, sync
from .auth import verify_password
from .config import REGULAR_SEASON_WEEKS, get_settings

log = logging.getLogger("nfl-picks")
BASE = Path(__file__).parent
settings = get_settings()
tz = ZoneInfo(settings.display_tz)

if not settings.secret_key:
    raise RuntimeError("SECRET_KEY is not set")


def _initial_sync() -> None:
    try:
        sync.run(settings)
    except Exception:  # noqa: BLE001
        log.exception("initial sync failed; the CronJob will retry")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init(settings.database_path)
    with db.session(settings.database_path) as conn:
        db.sync_users(conn, settings.users)
        empty = conn.execute("SELECT 1 FROM games LIMIT 1").fetchone() is None
    if empty and os.environ.get("SYNC_ON_STARTUP", "true").lower() == "true":
        threading.Thread(target=_initial_sync, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="nflpicks",
    max_age=60 * 60 * 24 * 60,
    same_site="lax",
    https_only=settings.cookie_secure,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _local(dt):
    return dt.astimezone(tz)


def _team_color(value: str | None) -> str:
    value = (value or "").lstrip("#")
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return f"#{value}"
    return "#172033"


def _text_on(value: str | None) -> str:
    """White or ink, whichever reads better on the team colour."""
    hexcode = _team_color(value)[1:]
    r, g, b = (int(hexcode[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#172033" if lum > 0.6 else "#ffffff"


templates.env.filters["day"] = lambda dt: _local(dt).strftime("%A, %-d %B")
templates.env.filters["time"] = lambda dt: _local(dt).strftime("%H:%M")
templates.env.filters["team_color"] = _team_color
templates.env.filters["text_on"] = _text_on


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _: LoginRequired):
    return RedirectResponse("/login", status_code=303)


def current_user(request: Request) -> dict:
    uid = request.session.get("uid")
    if not uid:
        raise LoginRequired()
    with db.session(settings.database_path) as conn:
        row = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (uid,)).fetchone()
    if not row or row["email"] not in {u.email for u in settings.users}:
        request.session.clear()
        raise LoginRequired()
    return dict(row)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login")
def login_form(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None, "error": None, "email": ""})


@app.post("/login")
async def login(request: Request, email: str = Form(""), password: str = Form("")):
    email = email.strip().lower()
    match = next((u for u in settings.users if u.email == email), None)
    if match and match.password_hash and verify_password(password, match.password_hash):
        with db.session(settings.database_path) as conn:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        request.session.clear()
        request.session["uid"] = row["id"]
        return RedirectResponse("/", status_code=303)
    await asyncio.sleep(1)  # slow down password guessing
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user": None, "error": "That email and password don't match.", "email": email},
        status_code=401,
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def home(request: Request):
    current_user(request)
    with db.session(settings.database_path) as conn:
        season = picks.current_season(conn)
        week = picks.current_week(conn, season)
    return RedirectResponse(f"/week/{week}", status_code=303)


@app.get("/week/{week}")
def week_page(request: Request, week: int):
    user = current_user(request)
    if not 1 <= week <= REGULAR_SEASON_WEEKS:
        return RedirectResponse("/", status_code=303)
    with db.session(settings.database_path) as conn:
        season = picks.current_season(conn)
        games = picks.week_view(conn, season, week)
        people = [dict(u) for u in picks.users(conn)]
        this_week = picks.current_week(conn, season)

    others = [u for u in people if u["id"] != user["id"]]
    for g in games:
        g["mine"] = g["picks"].get(user["id"])
        g["result"] = picks.outcome(g, user["id"])
        g["others"] = [
            {"name": u["name"], "pick": g["picks"].get(u["id"]), "result": picks.outcome(g, u["id"])}
            for u in others
        ]

    scores = [
        {
            "name": u["name"],
            "me": u["id"] == user["id"],
            "correct": sum(1 for g in games if picks.outcome(g, u["id"]) == "correct"),
        }
        for u in people
    ]
    graded = sum(1 for g in games if g["winner"])
    open_count = sum(1 for g in games if not g["locked"])
    missing = sum(1 for g in games if not g["locked"] and not g["mine"])
    days = [(day, list(items)) for day, items in groupby(games, key=lambda g: _local(g["kickoff_dt"]).date())]

    return templates.TemplateResponse(
        request,
        "week.html",
        {
            "user": user,
            "active": "week",
            "season": season,
            "week": week,
            "this_week": this_week,
            "days": days,
            "games": games,
            "scores": scores,
            "graded": graded,
            "open_count": open_count,
            "missing": missing,
            "prev_week": week - 1 if week > 1 else None,
            "next_week": week + 1 if week < REGULAR_SEASON_WEEKS else None,
            "error": request.query_params.get("error"),
        },
    )


@app.post("/pick")
def make_pick(request: Request, game_id: str = Form(...), pick: str = Form(...)) -> Response:
    user = current_user(request)
    wants_json = "application/json" in request.headers.get("accept", "")
    with db.session(settings.database_path) as conn:
        error = picks.save_pick(conn, user["id"], game_id, pick)
        row = conn.execute("SELECT week FROM games WHERE id = ?", (game_id,)).fetchone()
    if wants_json:
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=409)
        return JSONResponse({"ok": True, "game_id": game_id, "pick": pick})
    week = row["week"] if row else ""
    suffix = f"?error={quote(error)}" if error else ""
    return RedirectResponse(f"/week/{week}{suffix}#game-{game_id}", status_code=303)


@app.get("/results")
def results_page(request: Request):
    user = current_user(request)
    with db.session(settings.database_path) as conn:
        season = picks.current_season(conn)
        table = picks.standings(conn, season)
    return templates.TemplateResponse(
        request, "results.html", {"user": user, "active": "results", "season": season, "table": table}
    )
