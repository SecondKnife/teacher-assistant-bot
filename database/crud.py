"""
CRUD operations for the Teacher Bot database.
All functions are async-compatible.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Student,
    SyncLog,
    Task,
    TaskCategory,
    TaskPriority,
    TaskStatus,
    UserSetting,
)

logger = logging.getLogger(__name__)


# ─── Student CRUD ─────────────────────────────────────────


async def get_or_create_student(
    session: AsyncSession,
    name: str,
    class_name: str,
    subject: str = None,
) -> Student:
    """Get existing student or create a new one."""
    stmt = select(Student).where(
        Student.name == name,
        Student.class_name == class_name,
    )
    result = await session.execute(stmt)
    student = result.scalar_one_or_none()

    if student is None:
        student = Student(name=name, class_name=class_name, subject=subject)
        session.add(student)
        await session.flush()
        logger.info(f"Created new student: {name} ({class_name})")

    return student


async def search_students(
    session: AsyncSession,
    query: str,
    class_name: str = None,
) -> list[Student]:
    """Search students by name (partial match)."""
    stmt = select(Student).where(Student.name.ilike(f"%{query}%"))
    if class_name:
        stmt = stmt.where(Student.class_name == class_name)
    stmt = stmt.order_by(Student.class_name, Student.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_students_by_class(
    session: AsyncSession,
    class_name: str,
) -> list[Student]:
    """Get all students in a class."""
    stmt = (
        select(Student)
        .where(Student.class_name == class_name)
        .order_by(Student.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ─── Task CRUD ────────────────────────────────────────────


async def create_task(
    session: AsyncSession,
    title: str,
    description: str = None,
    category: TaskCategory = TaskCategory.TASK,
    deadline: datetime = None,
    priority: TaskPriority = TaskPriority.MEDIUM,
    student_id: int = None,
    source_file: str = None,
) -> Task:
    """Create a new task."""
    task = Task(
        title=title,
        description=description,
        category=category,
        deadline=deadline,
        priority=priority,
        student_id=student_id,
        source_file=source_file,
    )
    session.add(task)
    await session.flush()
    logger.info(f"Created task: {title}")
    return task


async def get_task_by_id(session: AsyncSession, task_id: int) -> Optional[Task]:
    """Get a task by ID."""
    stmt = select(Task).where(Task.id == task_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def mark_task_done(session: AsyncSession, task_id: int) -> Optional[Task]:
    """Mark a task as completed."""
    task = await get_task_by_id(session, task_id)
    if task:
        task.status = TaskStatus.DONE
        task.updated_at = datetime.utcnow()
        await session.flush()
        logger.info(f"Task {task_id} marked as done")
    return task


async def get_tasks_by_status(
    session: AsyncSession,
    status: TaskStatus,
    limit: int = 50,
) -> list[Task]:
    """Get tasks filtered by status."""
    stmt = (
        select(Task)
        .where(Task.status == status)
        .order_by(Task.deadline.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tasks_due_soon(
    session: AsyncSession,
    days_ahead: int = 3,
) -> list[Task]:
    """Get pending tasks with deadlines within the next N days."""
    now = datetime.utcnow()
    future = now + timedelta(days=days_ahead)
    stmt = (
        select(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.deadline.isnot(None),
            Task.deadline <= future,
        )
        .order_by(Task.deadline.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_today_tasks(session: AsyncSession) -> list[Task]:
    """Get all tasks due today."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    stmt = (
        select(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.deadline >= today_start,
            Task.deadline < today_end,
        )
        .order_by(Task.priority.desc(), Task.deadline.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tomorrow_tasks(session: AsyncSession) -> list[Task]:
    """Get all tasks due tomorrow."""
    now = datetime.utcnow()
    tomorrow_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)
    stmt = (
        select(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.deadline >= tomorrow_start,
            Task.deadline < tomorrow_end,
        )
        .order_by(Task.priority.desc(), Task.deadline.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_overdue_tasks(session: AsyncSession) -> list[Task]:
    """Get all overdue tasks (past deadline but not done)."""
    now = datetime.utcnow()
    stmt = (
        select(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.deadline.isnot(None),
            Task.deadline < now,
        )
        .order_by(Task.deadline.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tasks_for_student(
    session: AsyncSession,
    student_id: int,
    status: TaskStatus = None,
) -> list[Task]:
    """Get all tasks linked to a student."""
    stmt = select(Task).where(Task.student_id == student_id)
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.deadline.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tasks_by_class(
    session: AsyncSession,
    class_name: str,
    status: TaskStatus = None,
) -> list[Task]:
    """Get all tasks for students in a specific class."""
    stmt = (
        select(Task)
        .join(Student)
        .where(Student.class_name == class_name)
    )
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.deadline.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_overdue_tasks(session: AsyncSession) -> int:
    """Mark all past-deadline pending tasks as overdue. Returns count."""
    now = datetime.utcnow()
    stmt = (
        update(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.deadline.isnot(None),
            Task.deadline < now,
        )
        .values(status=TaskStatus.OVERDUE, updated_at=datetime.utcnow())
    )
    result = await session.execute(stmt)
    return result.rowcount


async def clear_tasks_from_source(session: AsyncSession, source_file: str) -> int:
    """Delete all tasks from a specific source file (for re-import)."""
    stmt = select(Task).where(Task.source_file == source_file)
    result = await session.execute(stmt)
    tasks = list(result.scalars().all())
    count = len(tasks)
    for task in tasks:
        await session.delete(task)
    await session.flush()
    logger.info(f"Cleared {count} tasks from source: {source_file}")
    return count


# ─── Statistics ───────────────────────────────────────────


async def get_task_statistics(session: AsyncSession) -> dict:
    """Get overall task statistics."""
    total_stmt = select(func.count(Task.id))
    pending_stmt = select(func.count(Task.id)).where(Task.status == TaskStatus.PENDING)
    done_stmt = select(func.count(Task.id)).where(Task.status == TaskStatus.DONE)
    overdue_stmt = select(func.count(Task.id)).where(Task.status == TaskStatus.OVERDUE)

    total = (await session.execute(total_stmt)).scalar() or 0
    pending = (await session.execute(pending_stmt)).scalar() or 0
    done = (await session.execute(done_stmt)).scalar() or 0
    overdue = (await session.execute(overdue_stmt)).scalar() or 0

    # Category breakdown
    category_stmt = (
        select(Task.category, func.count(Task.id))
        .where(Task.status == TaskStatus.PENDING)
        .group_by(Task.category)
    )
    category_result = await session.execute(category_stmt)
    categories = {str(row[0]): row[1] for row in category_result.all()}

    return {
        "total": total,
        "pending": pending,
        "done": done,
        "overdue": overdue,
        "completion_rate": round((done / total * 100) if total > 0 else 0, 1),
        "categories": categories,
    }


async def get_class_statistics(
    session: AsyncSession,
    class_name: str,
) -> dict:
    """Get statistics for a specific class."""
    students = await get_students_by_class(session, class_name)
    student_ids = [s.id for s in students]

    if not student_ids:
        return {"class_name": class_name, "student_count": 0, "tasks": {}}

    total_stmt = select(func.count(Task.id)).where(Task.student_id.in_(student_ids))
    pending_stmt = total_stmt.where(Task.status == TaskStatus.PENDING)
    done_stmt = (
        select(func.count(Task.id))
        .where(Task.student_id.in_(student_ids))
        .where(Task.status == TaskStatus.DONE)
    )
    overdue_stmt = (
        select(func.count(Task.id))
        .where(Task.student_id.in_(student_ids))
        .where(Task.status == TaskStatus.OVERDUE)
    )

    total = (await session.execute(total_stmt)).scalar() or 0
    pending = (await session.execute(pending_stmt)).scalar() or 0
    done = (await session.execute(done_stmt)).scalar() or 0
    overdue = (await session.execute(overdue_stmt)).scalar() or 0

    return {
        "class_name": class_name,
        "student_count": len(students),
        "total_tasks": total,
        "pending": pending,
        "done": done,
        "overdue": overdue,
    }


# ─── User Settings ───────────────────────────────────────


async def get_or_create_user_setting(
    session: AsyncSession,
    chat_id: str,
    username: str = None,
) -> UserSetting:
    """Get or create user settings."""
    stmt = select(UserSetting).where(UserSetting.chat_id == chat_id)
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()

    if setting is None:
        setting = UserSetting(chat_id=chat_id, username=username)
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for chat_id: {chat_id}")

    return setting


async def get_active_users(session: AsyncSession) -> list[UserSetting]:
    """Get all active users (for sending reminders)."""
    stmt = select(UserSetting).where(UserSetting.is_active == 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ─── Sync Log ────────────────────────────────────────────


async def create_sync_log(
    session: AsyncSession,
    file_name: str,
    file_id: str = None,
    modified_time: str = None,
    records_added: int = 0,
    records_updated: int = 0,
    status: str = "success",
    error_message: str = None,
) -> SyncLog:
    """Log a sync operation."""
    log = SyncLog(
        file_name=file_name,
        file_id=file_id,
        modified_time=modified_time,
        records_added=records_added,
        records_updated=records_updated,
        status=status,
        error_message=error_message,
    )
    session.add(log)
    await session.flush()
    return log


async def get_last_sync(
    session: AsyncSession,
    file_name: str = None,
) -> Optional[SyncLog]:
    """Get the most recent sync log."""
    stmt = select(SyncLog).order_by(SyncLog.synced_at.desc())
    if file_name:
        stmt = stmt.where(SyncLog.file_name == file_name)
    stmt = stmt.limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
