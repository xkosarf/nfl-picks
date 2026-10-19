"""Game, pick and scoring queries."""

import sqlite3
from datetime import datetime, timedelta

from .config import REGULAR_SEASON_WEEKS
from .db import utcnow


def current_season(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'season'").fetchone()
    if row:
        return int(row["value"])
    row = conn.execute("SELECT MAX(season) AS s FROM games").fetchone()
    if row and row["s"]:
        return int(row["s"])
    now = utcnow()
    # The NFL season that starts in September is named after that year.
    return now.year if now.month >= 3 else now.year - 1


def current_week(conn: sqlite3.Connection, season: int, now: datetime | None = None) -> int:
    """The first week that still has a game to be played or graded.

    After Monday night's game is final this rolls over to the next week,
    so on Tuesday the landing page already shows the upcoming games.
    """
    now = now or utcnow()
    cutoff = (now - timedelta(days=2)).isoformat()
    row = conn.execute(
        "SELECT MIN(week) AS w FROM games WHERE season = ? AND winner IS NULL AND kickoff > ?",
        (season, cutoff),
    ).fetchone()
    if row and row["w"]:
        return int(row["w"])
    row = conn.execute("SELECT MAX(week) AS w FROM games WHERE season = ?", (season,)).fetchone()
    return int(row["w"]) if row and row["w"] else 1


def users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, email, name FROM users ORDER BY id").fetchall()


def is_locked(game, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return game["state"] != "pre" or datetime.fromisoformat(game["kickoff"]) <= now


def week_view(conn: sqlite3.Connection, season: int, week: int, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    games = conn.execute(
        "SELECT * FROM games WHERE season = ? AND week = ? ORDER BY kickoff, id", (season, week)
    ).fetchall()
    picks: dict[str, dict[int, str]] = {}
    for row in conn.execute(
        "SELECT p.game_id, p.user_id, p.pick FROM picks p JOIN games g ON g.id = p.game_id "
        "WHERE g.season = ? AND g.week = ?",
        (season, week),
    ):
        picks.setdefault(row["game_id"], {})[row["user_id"]] = row["pick"]

    view = []
    for g in games:
        game = dict(g)
        game["kickoff_dt"] = datetime.fromisoformat(g["kickoff"])
        game["locked"] = is_locked(g, now)
        game["picks"] = picks.get(g["id"], {})
        view.append(game)
    return view


def outcome(game: dict, user_id: int) -> str | None:
    """'correct', 'wrong' or None (not graded yet). A tie is wrong for everyone."""
    if not game.get("winner"):
        return None
    return "correct" if game["picks"].get(user_id) == game["winner"] else "wrong"


def save_pick(conn: sqlite3.Connection, user_id: int, game_id: str, pick: str) -> str | None:
    """Store a pick. Returns an error message, or None on success."""
    if pick not in ("home", "away"):
        return "Pick the home or the away team."
    game = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if not game:
        return "That game doesn't exist."
    if is_locked(game):
        return "This game has kicked off, so its pick is locked."
    conn.execute(
        "INSERT INTO picks (user_id, game_id, pick, picked_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, game_id) DO UPDATE SET pick = excluded.pick, picked_at = excluded.picked_at",
        (user_id, game_id, pick, utcnow().isoformat()),
    )
    return None


def standings(conn: sqlite3.Connection, season: int) -> dict:
    """Correct picks per user per week, plus season totals."""
    people = users(conn)
    weeks = {
        w: {"week": w, "games": 0, "graded": 0, "correct": {u["id"]: 0 for u in people}}
        for w in range(1, REGULAR_SEASON_WEEKS + 1)
    }
    for row in conn.execute(
        "SELECT week, COUNT(*) AS games, SUM(winner IS NOT NULL) AS graded "
        "FROM games WHERE season = ? GROUP BY week",
        (season,),
    ):
        if row["week"] in weeks:
            weeks[row["week"]]["games"] = row["games"]
            weeks[row["week"]]["graded"] = row["graded"] or 0

    for row in conn.execute(
        "SELECT g.week, p.user_id, COUNT(*) AS correct FROM picks p JOIN games g ON g.id = p.game_id "
        "WHERE g.season = ? AND g.winner IS NOT NULL AND p.pick = g.winner GROUP BY g.week, p.user_id",
        (season,),
    ):
        if row["week"] in weeks and row["user_id"] in weeks[row["week"]]["correct"]:
            weeks[row["week"]]["correct"][row["user_id"]] = row["correct"]

    totals = {u["id"]: sum(w["correct"][u["id"]] for w in weeks.values()) for u in people}
    graded = sum(w["graded"] for w in weeks.values())
    for w in weeks.values():
        best = max(w["correct"].values(), default=0)
        leaders = [uid for uid, c in w["correct"].items() if c == best]
        w["leader"] = leaders[0] if w["graded"] and len(leaders) == 1 else None
    return {
        "users": people,
        "weeks": [w for w in weeks.values() if w["games"]],
        "totals": totals,
        "graded": graded,
    }
