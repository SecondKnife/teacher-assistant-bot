"""
Main entry point — initializes and runs the Telegram bot.
"""

import asyncio
import logging
import sys
from pathlib import Path

from telegram.ext import Application, CommandHandler

from config import config
from database.models import init_db, get_async_engine, get_async_session_factory
from bot import handlers
from services.scheduler import SchedulerService

# ─── Logging Setup ────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, config.log_level),
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            config.base_dir / "data" / "bot.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Called after the bot is initialized, before polling starts."""
    logger.info("Bot post_init: setting up database and scheduler...")

    # Ensure data directory exists
    data_dir = config.base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database
    engine = await init_db(config.database.url)
    sf = get_async_session_factory(engine)

    # Initialize scheduler
    scheduler = SchedulerService(config, bot_app=application)

    # Inject dependencies into handlers
    handlers.set_dependencies(sf, scheduler)

    # Start scheduler
    await scheduler.start()

    logger.info("✅ Bot is ready!")


async def post_shutdown(application: Application):
    """Called when the bot is shutting down."""
    logger.info("Bot shutting down...")


def main():
    """Build and run the bot."""
    if not config.telegram.bot_token:
        logger.error(
            "❌ TELEGRAM_BOT_TOKEN not set!\n"
            "Please copy .env.example to .env and fill in your bot token.\n"
            "Get a token from @BotFather on Telegram."
        )
        sys.exit(1)

    # Ensure data directory
    (config.base_dir / "data").mkdir(parents=True, exist_ok=True)

    # Build the application
    app = (
        Application.builder()
        .token(config.telegram.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # ── Register Command Handlers ─────────────────────────
    app.add_handler(CommandHandler("start", handlers.start_command))
    app.add_handler(CommandHandler("help", handlers.help_command))
    app.add_handler(CommandHandler("today", handlers.today_command))
    app.add_handler(CommandHandler("week", handlers.week_command))
    app.add_handler(CommandHandler("overdue", handlers.overdue_command))
    app.add_handler(CommandHandler("thongke", handlers.stats_command))
    app.add_handler(CommandHandler("hocsinh", handlers.student_command))
    app.add_handler(CommandHandler("lop", handlers.class_command))
    app.add_handler(CommandHandler("hoanthanh", handlers.complete_command))
    app.add_handler(CommandHandler("sync", handlers.sync_command))
    app.add_handler(CommandHandler("baocao", handlers.report_command))

    # ── Run ───────────────────────────────────────────────
    logger.info("🚀 Starting Teacher Assistant Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
