"""Pull the schedule and final scores from ESPN into the database.

Run by a Kubernetes CronJob every hour:

    python -m app.sync           # last, current and next week (+ full season once a day)
    python -m app.sync --all     # every regular-season week

Grading needs no separate step: a pick is correct when it matches the
stored winner, so the results page updates as soon as a game is final.
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from . import db
from .config import REGULAR_SEASON_WEEKS, Settings, get_settings
from .espn import REGULAR_SEASON, EspnClient

log = logging.getLogger("nfl-picks.sync")
FULL_SYNC_EVERY = timedelta(hours=20)


def weeks_to_sync(current_type: int, current_week: int) -> list[int]:
    if current_type == REGULAR_SEASON:
        week = current_week
    elif current_type < REGULAR_SEASON:  # preseason
        week = 1
    else:  # postseason / offseason
        week = REGULAR_SEASON_WEEKS
    return [w for w in (week - 1, week, week + 1) if 1 <= w <= REGULAR_SEASON_WEEKS]


def run(settings: Settings, client: EspnClient | None = None, full: bool = False) -> int:
    client = client or EspnClient(settings.espn_base)
    db.init(settings.database_path)

    espn_season, season_type, espn_week = client.current()
    season = settings.season or espn_season
    if settings.season and settings.season != espn_season:
        season_type, espn_week = REGULAR_SEASON, 1

    with db.session(settings.database_path) as conn:
        db.sync_users(conn, settings.users)
        db.set_meta(conn, "season", str(season))
        last_full = db.get_meta(conn, f"last_full_sync_{season}")
        has_games = conn.execute("SELECT 1 FROM games WHERE season = ? LIMIT 1", (season,)).fetchone()

    stale = last_full is None or db.utcnow() - datetime.fromisoformat(last_full) > FULL_SYNC_EVERY
    if full or not has_games or stale:
        weeks = list(range(1, REGULAR_SEASON_WEEKS + 1))
    else:
        weeks = weeks_to_sync(season_type, espn_week)

    count = 0
    for week in weeks:
        games = client.week_games(season, week)
        with db.session(settings.database_path) as conn:
            for game in games:
                db.upsert_game(conn, game)
        finals = sum(1 for g in games if g["winner"])
        log.info("season %s week %s: %s games, %s final", season, week, len(games), finals)
        count += len(games)

    if len(weeks) == REGULAR_SEASON_WEEKS:
        with db.session(settings.database_path) as conn:
            db.set_meta(conn, f"last_full_sync_{season}", db.utcnow().isoformat())
    return count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="sync every regular-season week")
    args = parser.parse_args()
    try:
        n = run(get_settings(), full=args.all)
    except Exception:  # noqa: BLE001 - log and fail the Job so Kubernetes shows it
        log.exception("sync failed")
        sys.exit(1)
    log.info("done, %s games synced", n)


if __name__ == "__main__":
    main()
