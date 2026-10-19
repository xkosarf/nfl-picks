import os
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_PATH=os.path.join(_tmp, "test.db"),
    SECRET_KEY="test-secret",
    COOKIE_SECURE="false",
    SYNC_ON_STARTUP="false",
    NFL_SEASON="2026",
)

from app.auth import hash_password  # noqa: E402

os.environ.update(
    USER1_EMAIL="filip@example.com",
    USER1_NAME="Filip",
    USER1_PASSWORD_HASH=hash_password("password-one"),
    USER2_EMAIL="tomas@example.com",
    USER2_NAME="Tomas",
    USER2_PASSWORD_HASH=hash_password("password-two"),
)


def espn_event(event_id, kickoff, home, away, state="pre", home_score=None, away_score=None, winner=None):
    completed = state == "post"
    def side(abbr, where, score, won):
        return {
            "homeAway": where,
            "winner": won,
            "score": "" if score is None else str(score),
            "team": {
                "abbreviation": abbr,
                "displayName": f"{abbr} Team",
                "shortDisplayName": abbr.title(),
                "color": "002244",
                "logo": f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbr.lower()}.png",
            },
        }
    return {
        "id": event_id,
        "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"),
        "status": {"type": {"name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED",
                            "state": state, "completed": completed}},
        "competitions": [{
            "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            "competitors": [
                side(home, "home", home_score, winner == "home"),
                side(away, "away", away_score, winner == "away"),
            ],
        }],
    }


@pytest.fixture
def now():
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


@pytest.fixture
def espn_weeks(now):
    """Week 1 is fully played (one tie), week 2 is half played, week 3 is ahead."""
    past = now - timedelta(days=10)
    return {
        1: [
            espn_event("101", past, "DEN", "SEA", "post", 17, 14, "home"),
            espn_event("102", past + timedelta(hours=3), "KC", "BUF", "post", 20, 27, "away"),
            espn_event("103", past + timedelta(days=1), "GB", "CHI", "post", 21, 21, None),
        ],
        2: [
            espn_event("201", now - timedelta(days=1), "DAL", "PHI", "post", 10, 24, "away"),
            espn_event("202", now - timedelta(minutes=30), "NYG", "WSH", "in", 7, 3),
            espn_event("203", now + timedelta(days=1), "SF", "LAR"),
        ],
        3: [espn_event("301", now + timedelta(days=7), "PIT", "BAL")],
    }


@pytest.fixture
def espn_client(espn_weeks):
    from app.espn import EspnClient

    def handler(request: httpx.Request):
        week = request.url.params.get("week")
        if week is None:
            return httpx.Response(200, json={"season": {"year": 2026, "type": 2}, "week": {"number": 2}, "events": []})
        return httpx.Response(200, json={"events": espn_weeks.get(int(week), [])})

    return EspnClient("https://espn.test", client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def fresh_db():
    from app import db
    from app.config import get_settings

    path = get_settings().database_path
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    db.init(path)
    with db.session(path) as conn:
        db.sync_users(conn, get_settings().users)
    return path


@pytest.fixture
def synced(fresh_db, espn_client):
    from app import sync
    from app.config import get_settings

    sync.run(get_settings(), client=espn_client, full=True)
    return fresh_db


@pytest.fixture
def client(synced):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, email="filip@example.com", password="password-one"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
