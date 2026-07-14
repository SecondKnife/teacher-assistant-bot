"""
Scheduler service — manages periodic jobs for:
- Daily reminders
- Google Drive sync
- Overdue task detection
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import AppConfig
from database.crud import (
    clear_tasks_from_source,
    create_sync_log,
    create_task,
    get_active_users,
    get_last_sync,
    get_or_create_student,
    get_overdue_tasks,
    get_task_statistics,
    get_tasks_due_soon,
    get_today_tasks,
    get_tomorrow_tasks,
    update_overdue_tasks,
)
from database.models import (
    TaskCategory,
    TaskPriority,
    TaskStatus,
    get_async_engine,
    get_async_session_factory,
)
from services.gdrive import GoogleDriveService
from services.parser import parse_file

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages all scheduled jobs."""

    def __init__(self, config: AppConfig, bot_app=None):
        self.config = config
        self.bot_app = bot_app  # telegram.ext.Application
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self._engine = None
        self._session_factory = None
        self._gdrive: GoogleDriveService | None = None

    async def start(self):
        """Initialize and start all scheduled jobs."""
        # Init database connection
        self._engine = get_async_engine(self.config.database.url)
        self._session_factory = get_async_session_factory(self._engine)

        # Init Google Drive if configured
        if self.config.gdrive.folder_id:
            self._gdrive = GoogleDriveService(
                service_account_file=self.config.gdrive.service_account_file,
                folder_id=self.config.gdrive.folder_id,
            )

        # ── Schedule Jobs ──────────────────────────────────

        # 1. Daily reminder
        hour, minute = map(int, self.config.scheduler.daily_reminder_time.split(":"))
        self.scheduler.add_job(
            self._daily_reminder_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_reminder",
            name="Nhắc nhở hàng ngày",
            replace_existing=True,
        )

        # 1b. Evening reminder
        eve_hour, eve_minute = map(int, self.config.scheduler.evening_reminder_time.split(":"))
        self.scheduler.add_job(
            self._evening_reminder_job,
            trigger=CronTrigger(hour=eve_hour, minute=eve_minute),
            id="evening_reminder",
            name="Tổng hợp buổi tối",
            replace_existing=True,
        )

        # 2. Google Drive sync
        if self._gdrive:
            self.scheduler.add_job(
                self._sync_gdrive_job,
                trigger=IntervalTrigger(
                    minutes=self.config.scheduler.sync_interval_minutes
                ),
                id="gdrive_sync",
                name="Đồng bộ Google Drive",
                replace_existing=True,
            )

        # 3. Overdue task checker (every hour)
        self.scheduler.add_job(
            self._check_overdue_job,
            trigger=IntervalTrigger(hours=1),
            id="overdue_check",
            name="Kiểm tra quá hạn",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Scheduler started with all jobs")

    async def stop(self):
        """Shutdown the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    # ─── Manual Triggers ──────────────────────────────────

    async def trigger_sync(self) -> dict:
        """Manually trigger a Google Drive sync. Returns sync results."""
        return await self._sync_gdrive_job()

    async def trigger_import_local(self, file_path: str) -> dict:
        """Import a local file (for testing without Google Drive)."""
        return await self._import_file(file_path, file_id=None, modified_time=None)

    # ─── Job Implementations ─────────────────────────────

    async def _daily_reminder_job(self):
        """Send daily summary to all active users."""
        logger.info("Running daily reminder job")

        async with self._session_factory() as session:
            # Update overdue tasks first
            overdue_count = await update_overdue_tasks(session)
            if overdue_count:
                logger.info(f"Marked {overdue_count} tasks as overdue")

            # Get today's tasks
            today_tasks = await get_today_tasks(session)
            due_soon = await get_tasks_due_soon(
                session, self.config.scheduler.remind_before_days
            )
            overdue = await get_overdue_tasks(session)
            stats = await get_task_statistics(session)

            await session.commit()

        # Build message
        message = self._build_daily_message(today_tasks, due_soon, overdue, stats)

        # Send to all active users
        if self.bot_app:
            async with self._session_factory() as session:
                users = await get_active_users(session)

            for user in users:
                try:
                    await self.bot_app.bot.send_message(
                        chat_id=user.chat_id,
                        text=message,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to send reminder to {user.chat_id}: {e}")

    async def _evening_reminder_job(self):
        """Send evening summary (pending and tomorrow's tasks) to all active users."""
        logger.info("Running evening reminder job")

        async with self._session_factory() as session:
            overdue_count = await update_overdue_tasks(session)
            if overdue_count:
                logger.info(f"Marked {overdue_count} tasks as overdue")

            overdue = await get_overdue_tasks(session)
            tomorrow_tasks = await get_tomorrow_tasks(session)
            # Find all pending tasks that aren't overdue and aren't due tomorrow
            due_soon = await get_tasks_due_soon(session, days_ahead=7)
            # Filter due_soon to find generic pending tasks to show
            stats = await get_task_statistics(session)

        # Build message
        message = self._build_evening_message(overdue, tomorrow_tasks, due_soon, stats)

        # Send to all active users
        if self.bot_app:
            async with self._session_factory() as session:
                users = await get_active_users(session)

            for user in users:
                try:
                    await self.bot_app.bot.send_message(
                        chat_id=user.chat_id,
                        text=message,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to send evening reminder to {user.chat_id}: {e}")

    async def _sync_gdrive_job(self) -> dict:
        """Sync files from Google Drive and import data."""
        logger.info("Running Google Drive sync job")
        results = {"synced": 0, "errors": [], "total_records": 0}

        if not self._gdrive:
            results["errors"].append("Google Drive not configured")
            return results

        # Download to temp directory within project
        download_dir = self.config.base_dir / "data" / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        try:
            synced_files = self._gdrive.sync_files(download_dir)
        except Exception as e:
            results["errors"].append(f"Sync failed: {e}")
            logger.error(f"Google Drive sync failed: {e}")
            return results

        for file_info in synced_files:
            try:
                import_result = await self._import_file(
                    file_path=file_info["local_path"],
                    file_id=file_info["file_id"],
                    modified_time=file_info["modified_time"],
                )
                results["synced"] += 1
                results["total_records"] += import_result.get("records_added", 0)
            except Exception as e:
                results["errors"].append(f"{file_info['file_name']}: {e}")
                logger.error(f"Import failed for {file_info['file_name']}: {e}")

        # Notify users about sync
        if self.bot_app and results["synced"] > 0:
            await self._notify_sync_complete(results)

        return results

    async def _import_file(
        self,
        file_path: str,
        file_id: str = None,
        modified_time: str = None,
    ) -> dict:
        """Parse and import a file into the database."""
        result = {"records_added": 0, "records_updated": 0}

        # Check if file has changed since last sync
        if file_id:
            async with self._session_factory() as session:
                last_sync = await get_last_sync(session, Path(file_path).name)
                if (
                    last_sync
                    and last_sync.modified_time == modified_time
                    and last_sync.status == "success"
                ):
                    logger.info(f"File unchanged, skipping: {file_path}")
                    return result

        # Parse the file
        parse_result = parse_file(file_path)

        if not parse_result.success:
            async with self._session_factory() as session:
                await create_sync_log(
                    session,
                    file_name=parse_result.file_name,
                    file_id=file_id,
                    modified_time=modified_time,
                    status="error",
                    error_message="; ".join(parse_result.errors),
                )
                await session.commit()
            raise Exception(f"Parse failed: {'; '.join(parse_result.errors)}")

        # Import records into database
        async with self._session_factory() as session:
            # Clear old data from this source
            await clear_tasks_from_source(session, parse_result.file_name)

            for record in parse_result.records:
                # Get or create student if applicable
                student_id = None
                if record.student_name and record.class_name:
                    student = await get_or_create_student(
                        session,
                        name=record.student_name,
                        class_name=record.class_name,
                        subject=record.subject,
                    )
                    student_id = student.id

                # Map category
                try:
                    category = TaskCategory(record.category)
                except ValueError:
                    category = TaskCategory.OTHER

                # Map priority
                try:
                    priority = TaskPriority(record.priority)
                except ValueError:
                    priority = TaskPriority.MEDIUM

                # Map status
                status_map = {
                    "done": TaskStatus.DONE,
                    "overdue": TaskStatus.OVERDUE,
                }
                status = status_map.get(record.status, TaskStatus.PENDING)

                await create_task(
                    session,
                    title=record.title,
                    description=record.description,
                    category=category,
                    deadline=record.deadline,
                    priority=priority,
                    student_id=student_id,
                    source_file=record.source_file,
                )
                result["records_added"] += 1

            # Log sync
            await create_sync_log(
                session,
                file_name=parse_result.file_name,
                file_id=file_id,
                modified_time=modified_time,
                records_added=result["records_added"],
            )

            await session.commit()

        logger.info(
            f"Imported {result['records_added']} records from {parse_result.file_name}"
        )
        return result

    async def _check_overdue_job(self):
        """Check and mark overdue tasks."""
        async with self._session_factory() as session:
            count = await update_overdue_tasks(session)
            await session.commit()
            if count:
                logger.info(f"Marked {count} tasks as overdue")

    # ─── Message Builders ─────────────────────────────────

    def _build_daily_message(
        self,
        today_tasks: list,
        due_soon: list,
        overdue: list,
        stats: dict,
    ) -> str:
        """Build the daily reminder message."""
        now = datetime.now()
        lines = [
            f"🌅 <b>Thông báo hàng ngày — {now.strftime('%d/%m/%Y')}</b>",
            "",
        ]

        # Overdue tasks (urgent!)
        if overdue:
            lines.append(f"🔴 <b>QUÁ HẠN ({len(overdue)} việc):</b>")
            for task in overdue[:5]:
                deadline_str = (
                    task.deadline.strftime("%d/%m")
                    if task.deadline
                    else "N/A"
                )
                lines.append(f"  ⚠️ [{deadline_str}] {task.title}")
            if len(overdue) > 5:
                lines.append(f"  ... và {len(overdue) - 5} việc khác")
            lines.append("")

        # Today's tasks
        if today_tasks:
            lines.append(f"📋 <b>HÔM NAY ({len(today_tasks)} việc):</b>")
            for task in today_tasks:
                emoji = {"nhắc nhở": "🔔", "khen thưởng": "⭐", "kỷ luật": "⚡"}.get(
                    str(task.category), "📌"
                )
                lines.append(f"  {emoji} {task.title}")
            lines.append("")
        else:
            lines.append("✅ Hôm nay không có deadline!\n")

        # Upcoming
        # Filter out today and overdue tasks from due_soon
        upcoming = [
            t for t in due_soon
            if t not in today_tasks and t not in overdue
        ]
        if upcoming:
            lines.append(f"📅 <b>SẮP TỚI ({len(upcoming)} việc):</b>")
            for task in upcoming[:5]:
                days_left = (task.deadline - now).days if task.deadline else "?"
                lines.append(f"  ⏰ [{days_left} ngày] {task.title}")
            lines.append("")

        # Stats summary
        lines.append("📊 <b>TỔNG QUAN:</b>")
        lines.append(
            f"  ✅ Hoàn thành: {stats['done']} | "
            f"⏳ Đang chờ: {stats['pending']} | "
            f"🔴 Quá hạn: {stats['overdue']}"
        )
        lines.append(f"  📈 Tiến độ: {stats['completion_rate']}%")

        return "\n".join(lines)

    def _build_evening_message(
        self,
        overdue: list,
        tomorrow_tasks: list,
        due_soon: list,
        stats: dict,
    ) -> str:
        """Build the evening summary message."""
        now = datetime.now()
        lines = [
            f"🌙 <b>Tổng hợp buổi tối — {now.strftime('%d/%m/%Y')}</b>",
            "",
        ]

        # Overdue tasks (urgent!)
        if overdue:
            lines.append(f"🔴 <b>CÒN TỒN ĐỌNG ({len(overdue)} việc):</b>")
            for task in overdue[:5]:
                deadline_str = (
                    task.deadline.strftime("%d/%m")
                    if task.deadline
                    else "N/A"
                )
                lines.append(f"  ⚠️ [{deadline_str}] {task.title}")
            if len(overdue) > 5:
                lines.append(f"  ... và {len(overdue) - 5} việc khác")
            lines.append("")

        # Tomorrow's tasks
        if tomorrow_tasks:
            lines.append(f"📅 <b>NGÀY MAI ({len(tomorrow_tasks)} việc):</b>")
            for task in tomorrow_tasks:
                emoji = {"nhắc nhở": "🔔", "khen thưởng": "⭐", "kỷ luật": "⚡"}.get(
                    str(task.category), "📌"
                )
                lines.append(f"  {emoji} {task.title}")
            lines.append("")
        else:
            lines.append("✅ Ngày mai không có deadline nào!\n")
            
        # Stats summary
        lines.append("📊 <b>TỔNG QUAN:</b>")
        lines.append(
            f"  ✅ Đã xong: {stats['done']} | "
            f"⏳ Đang chờ: {stats['pending']} | "
            f"🔴 Quá hạn: {stats['overdue']}"
        )

        return "\n".join(lines)

    async def _notify_sync_complete(self, results: dict):
        """Notify users about sync completion."""
        message = (
            f"🔄 <b>Đồng bộ Google Drive hoàn tất</b>\n"
            f"📁 Files: {results['synced']}\n"
            f"📝 Records: {results['total_records']}"
        )
        if results["errors"]:
            message += f"\n⚠️ Lỗi: {len(results['errors'])}"

        async with self._session_factory() as session:
            users = await get_active_users(session)

        for user in users:
            try:
                await self.bot_app.bot.send_message(
                    chat_id=user.chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to notify {user.chat_id}: {e}")
