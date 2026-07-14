import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from config import config
    from database.crud import get_tomorrow_tasks
    from services.scheduler import SchedulerService
    print("All modules imported successfully.")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
