"""
Telegram bot command handlers — all user-facing commands.
"""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from database.crud import (
    get_active_users,
    get_class_statistics,
    get_or_create_user_setting,
    get_overdue_tasks,
    get_task_by_id,
    get_task_statistics,
    get_tasks_by_class,
    get_tasks_due_soon,
    get_today_tasks,
    mark_task_done,
    search_students,
    get_tasks_for_student,
    update_overdue_tasks,
)
from database.models import TaskStatus, get_async_session_factory

logger = logging.getLogger(__name__)

# Will be set during bot initialization
session_factory = None
scheduler_service = None


def set_dependencies(sf, ss):
    """Inject dependencies (called from main.py)."""
    global session_factory, scheduler_service
    session_factory = sf
    scheduler_service = ss


# ─── /start ──────────────────────────────────────────────


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message and register user."""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or update.effective_user.first_name

    async with session_factory() as session:
        await get_or_create_user_setting(session, chat_id, username)
        await session.commit()

    welcome = (
        "🎓 <b>Chào mừng đến với Teacher Assistant Bot!</b>\n\n"
        "Bot giúp bạn quản lý công việc, nhắc nhở tự động "
        "và thống kê dựa trên tài liệu của bạn.\n\n"
        "📋 <b>Các lệnh chính:</b>\n"
        "  /today — Việc cần làm hôm nay\n"
        "  /week — Việc trong tuần tới\n"
        "  /thongke — Thống kê tổng quan\n"
        "  /hocsinh &lt;tên&gt; — Tra cứu học sinh\n"
        "  /lop &lt;tên lớp&gt; — Thống kê theo lớp\n"
        "  /hoanthanh &lt;id&gt; — Đánh dấu hoàn thành\n"
        "  /sync — Đồng bộ từ Google Drive\n"
        "  /baocao — Báo cáo chi tiết\n"
        "  /help — Xem hướng dẫn\n\n"
        f"✅ Đã đăng ký nhận nhắc nhở cho <b>{username}</b>!"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")


# ─── /help ───────────────────────────────────────────────


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information."""
    help_text = (
        "📖 <b>Hướng dẫn sử dụng Teacher Assistant Bot</b>\n\n"
        "🔄 <b>Đồng bộ dữ liệu:</b>\n"
        "  /sync — Đồng bộ ngay từ Google Drive\n\n"
        "📋 <b>Xem công việc:</b>\n"
        "  /today — Việc cần làm hôm nay\n"
        "  /week — Việc trong 7 ngày tới\n"
        "  /overdue — Các việc quá hạn\n\n"
        "📊 <b>Thống kê:</b>\n"
        "  /thongke — Tổng quan tất cả công việc\n"
        "  /lop 10A1 — Thống kê lớp 10A1\n"
        "  /baocao — Báo cáo chi tiết\n\n"
        "👩‍🎓 <b>Học sinh:</b>\n"
        "  /hocsinh Nguyễn — Tìm học sinh theo tên\n\n"
        "✅ <b>Cập nhật:</b>\n"
        "  /hoanthanh 5 — Hoàn thành việc #5\n\n"
        "⏰ <b>Nhắc nhở tự động:</b>\n"
        "  Bot sẽ gửi nhắc nhở mỗi sáng lúc 7:00\n"
        "  và cảnh báo trước deadline 3 ngày."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


# ─── /today ──────────────────────────────────────────────


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show tasks due today."""
    async with session_factory() as session:
        await update_overdue_tasks(session)
        tasks = await get_today_tasks(session)
        overdue = await get_overdue_tasks(session)
        await session.commit()

    now = datetime.now()
    lines = [f"📋 <b>Công việc hôm nay — {now.strftime('%d/%m/%Y')}</b>\n"]

    if overdue:
        lines.append(f"🔴 <b>QUÁ HẠN ({len(overdue)}):</b>")
        for task in overdue[:10]:
            student_info = ""
            if task.student_id:
                async with session_factory() as session:
                    from database.models import Student
                    from sqlalchemy import select
                    result = await session.execute(
                        select(Student).where(Student.id == task.student_id)
                    )
                    student = result.scalar_one_or_none()
                    if student:
                        student_info = f" ({student.name})"
            deadline = task.deadline.strftime("%d/%m") if task.deadline else ""
            lines.append(f"  ⚠️ #{task.id} [{deadline}] {task.title}{student_info}")
        lines.append("")

    if tasks:
        lines.append(f"📌 <b>HÔM NAY ({len(tasks)}):</b>")
        for task in tasks:
            emoji = _category_emoji(str(task.category))
            lines.append(f"  {emoji} #{task.id} {task.title}")
    else:
        lines.append("✅ Không có deadline hôm nay!")

    lines.append(f"\n💡 Dùng /hoanthanh &lt;id&gt; để đánh dấu xong")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /week ───────────────────────────────────────────────


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show tasks due in the next 7 days."""
    async with session_factory() as session:
        tasks = await get_tasks_due_soon(session, days_ahead=7)

    if not tasks:
        await update.message.reply_text("✅ Không có công việc nào trong 7 ngày tới!")
        return

    now = datetime.now()
    lines = [f"📅 <b>Công việc 7 ngày tới</b> (từ {now.strftime('%d/%m')})\n"]

    for task in tasks[:20]:
        if task.deadline:
            days_left = (task.deadline - now).days
            if days_left < 0:
                time_label = f"🔴 Trễ {abs(days_left)} ngày"
            elif days_left == 0:
                time_label = "🟡 Hôm nay"
            elif days_left == 1:
                time_label = "🟠 Ngày mai"
            else:
                time_label = f"🟢 {days_left} ngày nữa"
            date_str = task.deadline.strftime("%d/%m")
        else:
            time_label = "❓"
            date_str = "N/A"

        emoji = _category_emoji(str(task.category))
        lines.append(f"  {emoji} #{task.id} [{date_str}] {task.title}")
        lines.append(f"      └ {time_label}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /overdue ────────────────────────────────────────────


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all overdue tasks."""
    async with session_factory() as session:
        await update_overdue_tasks(session)
        tasks = await get_overdue_tasks(session)
        await session.commit()

    if not tasks:
        await update.message.reply_text("✅ Không có công việc quá hạn! 🎉")
        return

    lines = [f"🔴 <b>Công việc quá hạn ({len(tasks)})</b>\n"]
    for task in tasks[:20]:
        days_overdue = (datetime.now() - task.deadline).days if task.deadline else 0
        lines.append(
            f"  ⚠️ #{task.id} {task.title}\n"
            f"      └ Trễ {days_overdue} ngày (hạn: {task.deadline.strftime('%d/%m') if task.deadline else 'N/A'})"
        )

    lines.append(f"\n💡 Dùng /hoanthanh &lt;id&gt; để đánh dấu xong")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /thongke ────────────────────────────────────────────


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show overall statistics."""
    async with session_factory() as session:
        await update_overdue_tasks(session)
        stats = await get_task_statistics(session)
        await session.commit()

    # Progress bar
    rate = stats["completion_rate"]
    filled = int(rate / 10)
    bar = "█" * filled + "░" * (10 - filled)

    lines = [
        "📊 <b>THỐNG KÊ TỔNG QUAN</b>\n",
        f"📝 Tổng công việc: <b>{stats['total']}</b>",
        f"✅ Hoàn thành: <b>{stats['done']}</b>",
        f"⏳ Đang chờ: <b>{stats['pending']}</b>",
        f"🔴 Quá hạn: <b>{stats['overdue']}</b>",
        f"\n📈 Tiến độ: [{bar}] {rate}%",
    ]

    # Category breakdown
    if stats["categories"]:
        lines.append("\n📁 <b>Phân loại (đang chờ):</b>")
        cat_emojis = {
            "nhắc nhở": "🔔",
            "khen thưởng": "⭐",
            "kỷ luật": "⚡",
            "công việc": "📌",
            "khác": "📎",
        }
        for cat, count in stats["categories"].items():
            emoji = cat_emojis.get(cat, "📎")
            lines.append(f"  {emoji} {cat}: {count}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /hocsinh <name> ─────────────────────────────────────


async def student_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search and show student info."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Cách dùng: /hocsinh <tên>\nVí dụ: /hocsinh Nguyễn"
        )
        return

    query = " ".join(context.args)

    async with session_factory() as session:
        students = await search_students(session, query)

        if not students:
            await update.message.reply_text(f"❌ Không tìm thấy học sinh: {query}")
            return

        lines = [f"👩‍🎓 <b>Kết quả tìm kiếm: \"{query}\"</b>\n"]

        for student in students[:10]:
            tasks = await get_tasks_for_student(session, student.id)
            pending = [t for t in tasks if t.status == TaskStatus.PENDING]
            done = [t for t in tasks if t.status == TaskStatus.DONE]
            overdue = [t for t in tasks if t.status == TaskStatus.OVERDUE]

            lines.append(
                f"👤 <b>{student.name}</b> — {student.class_name}"
            )
            lines.append(
                f"   ✅ {len(done)} hoàn thành | "
                f"⏳ {len(pending)} đang chờ | "
                f"🔴 {len(overdue)} quá hạn"
            )

            # Show pending tasks
            for task in pending[:3]:
                emoji = _category_emoji(str(task.category))
                deadline = (
                    f" [{task.deadline.strftime('%d/%m')}]"
                    if task.deadline
                    else ""
                )
                lines.append(f"   {emoji} #{task.id}{deadline} {task.title}")

            if len(pending) > 3:
                lines.append(f"   ... và {len(pending) - 3} việc khác")
            lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /lop <class_name> ───────────────────────────────────


async def class_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show class statistics."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Cách dùng: /lop <tên lớp>\nVí dụ: /lop 10A1"
        )
        return

    class_name = " ".join(context.args)

    async with session_factory() as session:
        stats = await get_class_statistics(session, class_name)

    if stats["student_count"] == 0:
        await update.message.reply_text(f"❌ Không tìm thấy lớp: {class_name}")
        return

    lines = [
        f"🏫 <b>Thống kê lớp {class_name}</b>\n",
        f"👥 Số học sinh: <b>{stats['student_count']}</b>",
        f"📝 Tổng việc: <b>{stats['total_tasks']}</b>",
        f"✅ Hoàn thành: <b>{stats['done']}</b>",
        f"⏳ Đang chờ: <b>{stats['pending']}</b>",
        f"🔴 Quá hạn: <b>{stats['overdue']}</b>",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── /hoanthanh <id> ─────────────────────────────────────


async def complete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark a task as complete."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Cách dùng: /hoanthanh <id>\nVí dụ: /hoanthanh 5"
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID phải là số. Ví dụ: /hoanthanh 5")
        return

    async with session_factory() as session:
        task = await mark_task_done(session, task_id)
        await session.commit()

    if task:
        await update.message.reply_text(
            f"✅ Đã hoàn thành: <b>#{task.id} {task.title}</b>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(f"❌ Không tìm thấy công việc #{task_id}")


# ─── /sync ───────────────────────────────────────────────


async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger Google Drive sync."""
    await update.message.reply_text("🔄 Đang đồng bộ từ Google Drive...")

    try:
        results = await scheduler_service.trigger_sync()

        if results.get("errors"):
            error_text = "\n".join(f"  ⚠️ {e}" for e in results["errors"])
            await update.message.reply_text(
                f"🔄 Đồng bộ hoàn tất (có lỗi):\n"
                f"📁 Files: {results['synced']}\n"
                f"📝 Records: {results['total_records']}\n"
                f"\n❌ Lỗi:\n{error_text}",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"✅ Đồng bộ thành công!\n"
                f"📁 Files: {results['synced']}\n"
                f"📝 Records: {results['total_records']}"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi đồng bộ: {e}")


# ─── /baocao ─────────────────────────────────────────────


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate detailed report."""
    async with session_factory() as session:
        await update_overdue_tasks(session)
        stats = await get_task_statistics(session)
        overdue = await get_overdue_tasks(session)
        due_soon = await get_tasks_due_soon(session, days_ahead=7)
        await session.commit()

    now = datetime.now()
    lines = [
        f"📄 <b>BÁO CÁO CHI TIẾT</b>",
        f"📅 Ngày: {now.strftime('%d/%m/%Y %H:%M')}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # Overall stats
    rate = stats["completion_rate"]
    filled = int(rate / 10)
    bar = "█" * filled + "░" * (10 - filled)

    lines.extend([
        f"\n📊 <b>TỔNG QUAN</b>",
        f"  Tổng: {stats['total']} | ✅ {stats['done']} | ⏳ {stats['pending']} | 🔴 {stats['overdue']}",
        f"  Tiến độ: [{bar}] {rate}%",
    ])

    # Overdue section
    if overdue:
        lines.append(f"\n🔴 <b>QUÁ HẠN ({len(overdue)} việc)</b>")
        for task in overdue[:10]:
            days = (now - task.deadline).days if task.deadline else 0
            lines.append(f"  ⚠️ #{task.id} {task.title} (trễ {days} ngày)")

    # Upcoming section
    if due_soon:
        upcoming = [t for t in due_soon if t not in overdue]
        if upcoming:
            lines.append(f"\n📅 <b>SẮP TỚI ({len(upcoming)} việc)</b>")
            for task in upcoming[:10]:
                days_left = (task.deadline - now).days if task.deadline else "?"
                date_str = task.deadline.strftime("%d/%m") if task.deadline else "N/A"
                lines.append(f"  ⏰ #{task.id} [{date_str}] {task.title} ({days_left} ngày)")

    # Categories
    if stats["categories"]:
        lines.append(f"\n📁 <b>PHÂN LOẠI</b>")
        for cat, count in stats["categories"].items():
            lines.append(f"  • {cat}: {count}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 <i>Teacher Assistant Bot</i>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── Helper ──────────────────────────────────────────────


def _category_emoji(category: str) -> str:
    """Get emoji for task category."""
    return {
        "nhắc nhở": "🔔",
        "khen thưởng": "⭐",
        "kỷ luật": "⚡",
        "công việc": "📌",
        "khác": "📎",
    }.get(category, "📌")
