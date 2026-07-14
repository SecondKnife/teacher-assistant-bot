import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config
from database.models import init_db, get_async_session_factory
from services.scheduler import SchedulerService
from mock_data.generate_mock import create_student_excel, create_task_word

async def main():
    engine = await init_db(config.database.url)
    sf = get_async_session_factory(engine)
    scheduler = SchedulerService(config)
    scheduler._engine = engine
    scheduler._session_factory = sf
    
    print("Generating mock data...")
    excel_path = create_student_excel()
    word_path = create_task_word()
    
    print("Importing mock data into production database...")
    await scheduler.trigger_import_local(str(excel_path))
    await scheduler.trigger_import_local(str(word_path))
    print("Data imported successfully!")

if __name__ == "__main__":
    asyncio.run(main())
