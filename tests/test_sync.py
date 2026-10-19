from app import db, picks
from app.auth import hash_password, verify_password
from app.espn import parse_event
from app.sync import weeks_to_sync

from .conftest import espn_event


def test_parse_final_and_tie(now):
    final = parse_event(espn_event("1", now, "DEN", "SEA", "post", 17, 14, "home"), 2026, 6)
    assert final["winner"] == "home" and final["home_score"] == 17 and final["away_abbr"] == "SEA"
    tie = parse_event(espn_event("2", now, "GB", "CHI", "post", 21, 21), 2026, 6)
    assert tie["winner"] == "tie"
    upcoming = parse_event(espn_event("3", now, "SF", "LAR"), 2026, 6)
    assert upcoming["winner"] is None and upcoming["home_score"] is None


def test_live_game_is_not_graded(now):
    live = parse_event(espn_event("4", now, "NYG", "WSH", "in", 7, 3), 2026, 6)
    assert live["winner"] is None and live["home_score"] == 7


def test_weeks_to_sync():
    assert weeks_to_sync(2, 7) == [6, 7, 8]
    assert weeks_to_sync(2, 1) == [1, 2]
    assert weeks_to_sync(2, 18) == [17, 18]
    assert weeks_to_sync(1, 3) == [1, 2]       # preseason
    assert weeks_to_sync(3, 2) == [17, 18]     # playoffs


def test_sync_stores_games(synced):
    with db.session(synced) as conn:
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 7
        assert picks.current_week(conn, 2026) == 2


def test_resync_updates_scores(synced, espn_client, espn_weeks, now):
    from app import sync
    from app.config import get_settings

    espn_weeks[2][1] = espn_event("202", now, "NYG", "WSH", "post", 7, 10, "away")
    sync.run(get_settings(), client=espn_client)
    with db.session(synced) as conn:
        row = conn.execute("SELECT winner, away_score FROM games WHERE id = '202'").fetchone()
    assert row["winner"] == "away" and row["away_score"] == 10


def test_password_hash_roundtrip():
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")
