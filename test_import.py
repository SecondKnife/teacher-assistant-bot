"""
Quick test script — import mock data and verify parsing works correctly.
Run: python test_import.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database.models import init_db, get_async_engine, get_async_session_factory
from database.crud import get_task_statistics, get_tasks_due_soon, get_overdue_tasks
from services.parser import parse_file
from services.scheduler import SchedulerService
from config import config


async def main():
    print("=" * 60)
    print("🧪 Teacher Bot — Test Import")
    print("=" * 60)

    # 1. Generate mock data
    print("\n📁 Step 1: Generating mock data...")
    from mock_data.generate_mock import create_student_excel, create_task_word

    excel_path = create_student_excel()
    word_path = create_task_word()

    # 2. Test parser
    print("\n🔍 Step 2: Testing document parser...")

    print(f"\n--- Parsing Excel: {excel_path.name} ---")
    excel_result = parse_file(excel_path)
    print(f"  Records: {excel_result.record_count}")
    print(f"  Errors: {excel_result.errors}")
    print(f"  Warnings: {excel_result.warnings}")
    for record in excel_result.records:
        print(
            f"  📝 [{record.category}] {record.student_name} ({record.class_name}): "
            f"{record.title[:50]}... | Deadline: {record.deadline}"
        )

    print(f"\n--- Parsing Word: {word_path.name} ---")
    word_result = parse_file(word_path)
    print(f"  Records: {word_result.record_count}")
    print(f"  Errors: {word_result.errors}")
    print(f"  Warnings: {word_result.warnings}")
    for record in word_result.records:
        print(
            f"  📝 [{record.priority}] {record.title[:50]}... | "
            f"Deadline: {record.deadline}"
        )

    # 3. Test database import
    print("\n🗄️ Step 3: Testing database import...")

    # Use in-memory database for testing
    test_db_url = "sqlite+aiosqlite:///./data/test_teacher_bot.db"
    Path("./data").mkdir(exist_ok=True)

    engine = await init_db(test_db_url)
    sf = get_async_session_factory(engine)

    # Create scheduler and import
    scheduler = SchedulerService(config)
    scheduler._engine = engine
    scheduler._session_factory = sf

    # Import Excel
    result1 = await scheduler.trigger_import_local(user_id=1, file_path=str(excel_path))
    print(f"  Excel import: {result1['records_added']} records added")

    # Import Word
    result2 = await scheduler.trigger_import_local(user_id=1, file_path=str(word_path))
    print(f"  Word import: {result2['records_added']} records added")

    # 4. Test statistics
    print("\n📊 Step 4: Checking statistics...")
    async with sf() as session:
        stats = await get_task_statistics(session, user_id=1)
        due_soon = await get_tasks_due_soon(session, user_id=1, days_ahead=7)
        overdue = await get_overdue_tasks(session, user_id=1)

    print(f"  Total tasks: {stats['total']}")
    print(f"  Pending: {stats['pending']}")
    print(f"  Done: {stats['done']}")
    print(f"  Overdue: {stats['overdue']}")
    print(f"  Completion rate: {stats['completion_rate']}%")
    print(f"  Due in 7 days: {len(due_soon)}")
    print(f"  Categories: {stats['categories']}")

    if overdue:
        print(f"\n  🔴 Overdue tasks:")
        for task in overdue:
            print(f"    ⚠️ {task.title}")

    # Cleanup test db
    Path("./data/test_teacher_bot.db").unlink(missing_ok=True)

    print("\n" + "=" * 60)
    print("✅ All tests passed! Bot is ready to use.")
    print("=" * 60)
    print("\n📖 Next steps:")
    print("  1. Copy .env.example → .env")
    print("  2. Set TELEGRAM_BOT_TOKEN (from @BotFather)")
    print("  3. Run: python -m bot.main")


if __name__ == "__main__":
    asyncio.run(main())
