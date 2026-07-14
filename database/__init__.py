"""
SQLAlchemy database models for the Teacher Bot.
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


# ─── Enums ────────────────────────────────────────────────


class TaskCategory(str, PyEnum):
    REMINDER = "nhắc nhở"
    REWARD = "khen thưởng"
    DISCIPLINE = "kỷ luật"
    TASK = "công việc"
    OTHER = "khác"


class TaskStatus(str, PyEnum):
    PENDING = "pending"
    DONE = "done"
    OVERDUE = "overdue"


class TaskPriority(str, PyEnum):
    HIGH = "cao"
    MEDIUM = "trung bình"
    LOW = "thấp"


# ─── Models ───────────────────────────────────────────────


class Student(Base):
    """Represents a student being tracked."""

    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)
    class_name = Column(String(50), nullable=False, index=True)
    subject = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tasks = relationship("Task", back_populates="student", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", "class_name", name="uq_student_name_class"),
    )

    def __repr__(self):
        return f"<Student(id={self.id}, name='{self.name}', class='{self.class_name}')>"


class Task(Base):
    """
    Represents a task/action item.
    Can be linked to a student (e.g., remind student X) or standalone (e.g., submit lesson plan).
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(
        Enum(TaskCategory, values_callable=lambda x: [e.value for e in x]),
        default=TaskCategory.TASK,
        nullable=False,
    )
    deadline = Column(DateTime, nullable=True, index=True)
    priority = Column(
        Enum(TaskPriority, values_callable=lambda x: [e.value for e in x]),
        default=TaskPriority.MEDIUM,
    )
    status = Column(
        Enum(TaskStatus, values_callable=lambda x: [e.value for e in x]),
        default=TaskStatus.PENDING,
        index=True,
    )
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    source_file = Column(String(500), nullable=True)
    reminder_sent = Column(Integer, default=0)  # Track how many reminders sent
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    student = relationship("Student", back_populates="tasks")

    def __repr__(self):
        return f"<Task(id={self.id}, title='{self.title[:30]}...', status='{self.status}')>"


class UserSetting(Base):
    """Per-user settings for the bot."""

    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(100), unique=True, nullable=False, index=True)
    username = Column(String(200), nullable=True)
    reminder_time = Column(String(10), default="07:00")
    remind_before_days = Column(Integer, default=3)
    sync_interval_minutes = Column(Integer, default=30)
    is_active = Column(Integer, default=1)  # SQLite doesn't have native boolean
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserSetting(chat_id='{self.chat_id}', reminder='{self.reminder_time}')>"


class SyncLog(Base):
    """Tracks Google Drive sync history."""

    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(500), nullable=False)
    file_id = Column(String(200), nullable=True)
    modified_time = Column(String(50), nullable=True)
    records_added = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    status = Column(String(50), default="success")
    error_message = Column(Text, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SyncLog(file='{self.file_name}', status='{self.status}')>"


# ─── Engine & Session Factory ─────────────────────────────


def get_async_engine(database_url: str):
    """Create an async SQLAlchemy engine."""
    return create_async_engine(database_url, echo=False, future=True)


def get_async_session_factory(engine):
    """Create an async session factory."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(database_url: str):
    """Initialize database — create all tables."""
    engine = get_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine
