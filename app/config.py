"""Settings read from environment variables."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserConfig:
    email: str
    name: str
    password_hash: str


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_users() -> list[UserConfig]:
    users = []
    for i in (1, 2, 3, 4):
        email = os.environ.get(f"USER{i}_EMAIL", "").strip().lower()
        if not email:
            continue
        users.append(
            UserConfig(
                email=email,
                name=os.environ.get(f"USER{i}_NAME", email.split("@")[0]).strip(),
                password_hash=os.environ.get(f"USER{i}_PASSWORD_HASH", "").strip(),
            )
        )
    return users


@dataclass(frozen=True)
class Settings:
    database_path: str = field(default_factory=lambda: os.environ.get("DATABASE_PATH", "./data/nfl.db"))
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))
    display_tz: str = field(default_factory=lambda: os.environ.get("DISPLAY_TZ", "Europe/Bratislava"))
    # Leave empty to follow the season ESPN currently reports.
    season: int | None = field(
        default_factory=lambda: int(os.environ["NFL_SEASON"]) if os.environ.get("NFL_SEASON") else None
    )
    # Optional override; app/espn.py has working defaults.
    espn_base: str | None = field(default_factory=lambda: os.environ.get("ESPN_BASE") or None)
    cookie_secure: bool = field(default_factory=lambda: _env_bool("COOKIE_SECURE", True))
    users: list[UserConfig] = field(default_factory=_load_users)


REGULAR_SEASON_WEEKS = 18


def get_settings() -> Settings:
    return Settings()
