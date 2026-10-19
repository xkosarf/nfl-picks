"""Fill a local database with a made-up week for trying the UI without ESPN.

    DATABASE_PATH=./data/demo.db python scripts/seed_demo.py
"""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402

TEAMS = {
    "SEA": ("Seattle Seahawks", "Seahawks", "002a5c"), "DEN": ("Denver Broncos", "Broncos", "fb4f14"),
    "BUF": ("Buffalo Bills", "Bills", "00338d"), "KC": ("Kansas City Chiefs", "Chiefs", "e31837"),
    "GB": ("Green Bay Packers", "Packers", "204e32"), "CHI": ("Chicago Bears", "Bears", "0b1c3a"),
    "PHI": ("Philadelphia Eagles", "Eagles", "06424d"), "DAL": ("Dallas Cowboys", "Cowboys", "002a5c"),
    "SF": ("San Francisco 49ers", "49ers", "aa0000"), "LAR": ("Los Angeles Rams", "Rams", "003594"),
    "PIT": ("Pittsburgh Steelers", "Steelers", "ffb612"), "BAL": ("Baltimore Ravens", "Ravens", "29126f"),
    "MIA": ("Miami Dolphins", "Dolphins", "008e97"), "NYJ": ("New York Jets", "Jets", "115740"),
    "DET": ("Detroit Lions", "Lions", "0076b6"), "MIN": ("Minnesota Vikings", "Vikings", "4f2683"),
}


def game(gid, week, kickoff, home, away, state="pre", hs=None, as_=None):
    g = {"id": gid, "season": 2026, "week": week, "kickoff": kickoff.isoformat(), "state": state,
         "status": "STATUS_FINAL" if state == "post" else "STATUS_SCHEDULED",
         "home_score": hs, "away_score": as_, "winner": None}
    if state == "post":
        g["winner"] = "tie" if hs == as_ else ("home" if hs > as_ else "away")
    for key, abbr in (("home", home), ("away", away)):
        name, short, color = TEAMS[abbr]
        g.update({f"{key}_abbr": abbr, f"{key}_name": name, f"{key}_short": short, f"{key}_color": color,
                  f"{key}_logo": f"https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/{abbr.lower()}.png"})
    return g


def main():
    s = get_settings()
    db.init(s.database_path)
    now = db.utcnow().replace(minute=0, second=0, microsecond=0)
    games = [
        game("601", 6, now - timedelta(days=9), "DEN", "SEA", "post", 17, 14),
        game("602", 6, now - timedelta(days=6), "KC", "BUF", "post", 20, 27),
        game("603", 6, now - timedelta(days=6, hours=-3), "GB", "CHI", "post", 24, 24),
        game("701", 7, now - timedelta(days=3), "DAL", "PHI", "post", 13, 27),
        game("702", 7, now - timedelta(hours=1), "LAR", "SF", "in", 10, 14),
        game("703", 7, now + timedelta(hours=3), "BAL", "PIT"),
        game("704", 7, now + timedelta(hours=3), "NYJ", "MIA"),
        game("705", 7, now + timedelta(days=1), "MIN", "DET"),
        game("801", 8, now + timedelta(days=7), "SEA", "KC"),
    ]
    with db.session(s.database_path) as conn:
        db.sync_users(conn, s.users)
        db.set_meta(conn, "season", "2026")
        for g in games:
            db.upsert_game(conn, g)
        ids = [r["id"] for r in conn.execute("SELECT id FROM users ORDER BY id")]
        if len(ids) >= 2:
            a, b = ids[:2]
            for uid, gid, pick in [(a, "601", "home"), (a, "602", "away"), (a, "603", "home"),
                                   (b, "601", "away"), (b, "602", "away"), (b, "603", "away"),
                                   (a, "701", "away"), (b, "701", "home"), (a, "702", "away"),
                                   (b, "702", "home"), (a, "703", "home"), (b, "703", "away"),
                                   (b, "705", "away")]:
                conn.execute("INSERT OR REPLACE INTO picks VALUES (?, ?, ?, ?)", (uid, gid, pick, now.isoformat()))
    print(f"Demo data written to {s.database_path}")


if __name__ == "__main__":
    main()
