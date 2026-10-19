"""SQLite storage. One small file on a persistent volume is plenty for two players."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id      INTEGER PRIMARY KEY,
    email   TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id          TEXT PRIMARY KEY,           -- ESPN event id
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    kickoff     TEXT NOT NULL,              -- ISO 8601, UTC
    state       TEXT NOT NULL,              -- pre | in | post
    status      TEXT NOT NULL,              -- ESPN status name, e.g. STATUS_FINAL
    home_abbr   TEXT NOT NULL,
    home_name   TEXT NOT NULL,
    home_short  TEXT NOT NULL,
    home_color  TEXT,
    home_logo   TEXT,
    home_score  INTEGER,
    away_abbr   TEXT NOT NULL,
    away_name   TEXT NOT NULL,
    away_short  TEXT NOT NULL,
    away_color  TEXT,
    away_logo   TEXT,
    away_score  INTEGER,
    winner      TEXT,                       -- home | away | tie | NULL until final
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS games_season_week ON games (season, week, kickoff);

CREATE TABLE IF NOT EXISTS picks (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    game_id     TEXT NOT NULL REFERENCES games(id),
    pick        TEXT NOT NULL CHECK (pick IN ('home', 'away')),
    picked_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, game_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def session(path: str):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: str) -> None:
    with session(path) as conn:
        conn.executescript(SCHEMA)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def sync_users(conn: sqlite3.Connection, users) -> None:
    """Make sure every configured user has a row; names follow the config."""
    for u in users:
        conn.execute(
            "INSERT INTO users (email, name) VALUES (?, ?) ON CONFLICT(email) DO UPDATE SET name = excluded.name",
            (u.email, u.name),
        )


GAME_COLUMNS = (
    "id", "season", "week", "kickoff", "state", "status",
    "home_abbr", "home_name", "home_short", "home_color", "home_logo", "home_score",
    "away_abbr", "away_name", "away_short", "away_color", "away_logo", "away_score",
    "winner",
)


def upsert_game(conn: sqlite3.Connection, game: dict) -> None:
    cols = ", ".join(GAME_COLUMNS) + ", updated_at"
    placeholders = ", ".join("?" for _ in GAME_COLUMNS) + ", ?"
    updates = ", ".join(f"{c} = excluded.{c}" for c in GAME_COLUMNS if c != "id")
    conn.execute(
        f"INSERT INTO games ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}, updated_at = excluded.updated_at",
        [game.get(c) for c in GAME_COLUMNS] + [utcnow().isoformat()],
    )
