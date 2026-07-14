"""
Application configuration — loads from environment variables.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    admin_telegram_id: str = field(
        default_factory=lambda: os.getenv("ADMIN_TELEGRAM_ID", "")
    )


@dataclass(frozen=True)
class GoogleDriveConfig:
    service_account_file: str = field(
        default_factory=lambda: os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE",
            str(BASE_DIR / "credentials" / "service_account.json"),
        )
    )


@dataclass(frozen=True)
class SchedulerConfig:
    daily_reminder_time: str = field(
        default_factory=lambda: os.getenv("DAILY_REMINDER_TIME", "07:00")
    )
    evening_reminder_time: str = field(
        default_factory=lambda: os.getenv("EVENING_REMINDER_TIME", "21:00")
    )
    remind_before_days: int = field(
        default_factory=lambda: int(os.getenv("REMIND_BEFORE_DAYS", "3"))
    )
    sync_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("SYNC_INTERVAL_MINUTES", "30"))
    )


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'teacher_bot.db'}",
        )
    )


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    gdrive: GoogleDriveConfig = field(default_factory=GoogleDriveConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    timezone: str = field(
        default_factory=lambda: os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    base_dir: Path = BASE_DIR


# Singleton config
config = AppConfig()
