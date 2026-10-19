"""Client for ESPN's public (undocumented) NFL scoreboard JSON.

Everything ESPN-specific lives in this file, so switching to another data
provider later means rewriting only this module.
"""

from datetime import datetime, timezone

import httpx

REGULAR_SEASON = 2
TIMEOUT = httpx.Timeout(20.0)
HEADERS = {"User-Agent": "nfl-picks/1.0 (+https://nfl.kosar.sk)"}


def _parse_kickoff(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _score(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_event(event: dict, season: int, week: int) -> dict | None:
    """Turn one ESPN event into a flat game dict, or None if it is unusable."""
    try:
        comp = event["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = sides["home"], sides["away"]
    except (KeyError, IndexError):
        return None

    status = (comp.get("status") or event.get("status") or {}).get("type", {})
    state = status.get("state", "pre")
    completed = bool(status.get("completed"))
    home_score, away_score = _score(home.get("score")), _score(away.get("score"))

    winner = None
    if completed:
        if home.get("winner") is True:
            winner = "home"
        elif away.get("winner") is True:
            winner = "away"
        elif home_score is not None and home_score == away_score:
            winner = "tie"
        elif home_score is not None and away_score is not None:
            winner = "home" if home_score > away_score else "away"

    def team(side: dict, key: str):
        t = side.get("team", {})
        return {
            f"{key}_abbr": t.get("abbreviation", "?"),
            f"{key}_name": t.get("displayName", t.get("name", "?")),
            f"{key}_short": t.get("shortDisplayName", t.get("name", "?")),
            f"{key}_color": t.get("color"),
            f"{key}_logo": t.get("logo"),
        }

    game = {
        "id": str(event["id"]),
        "season": season,
        "week": week,
        "kickoff": _parse_kickoff(comp.get("date") or event["date"]),
        "state": state,
        "status": status.get("name", "STATUS_SCHEDULED"),
        # Scores only mean something once the game has started.
        "home_score": home_score if state != "pre" else None,
        "away_score": away_score if state != "pre" else None,
        "winner": winner,
    }
    game.update(team(home, "home"))
    game.update(team(away, "away"))
    return game


class EspnClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)

    def _get(self, params: dict | None = None) -> dict:
        resp = self.client.get(f"{self.base_url}/scoreboard", params=params)
        resp.raise_for_status()
        return resp.json()

    def current(self) -> tuple[int, int, int]:
        """Return (season year, season type, week number) that ESPN considers current."""
        data = self._get()
        season = data.get("season", {})
        week = data.get("week", {})
        return int(season.get("year")), int(season.get("type", REGULAR_SEASON)), int(week.get("number", 1))

    def week_games(self, season: int, week: int) -> list[dict]:
        data = self._get({"seasontype": REGULAR_SEASON, "week": week, "dates": season})
        games = []
        for event in data.get("events", []):
            game = parse_event(event, season, week)
            if game:
                games.append(game)
        return games
