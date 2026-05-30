import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.models import SourceRegistry
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SourceRegistry))
        rows = result.scalars().all()
        print(f'Found {len(rows)} sources in DB:')
        for r in rows:
            print(f'  {r.source_id} | {r.system_type} | enabled={r.enabled}')

asyncio.run(check())
