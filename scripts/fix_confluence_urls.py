import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.models import SourceRegistry
from sqlalchemy import select, update


CONFLUENCE_URL_MAP = {
    # source_id fragment → correct base_url
    # Add your actual source_ids here
    "apache-spark-wiki":  "https://cwiki.apache.org/confluence",
    "apache-kafka-wiki":  "https://cwiki.apache.org/confluence",
    "apache-hadoop-wiki": "https://cwiki.apache.org/confluence",
    "apache-flink-wiki":  "https://cwiki.apache.org/confluence",
}

ATLASSIAN_CORRECT_URL = "https://cpp3-hpe.atlassian.net/wiki"

MOCK_DOMAINS = [
    "confluence.example.com",
    "localhost",
    "127.0.0.1",
    "example.com",
]


async def fix():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SourceRegistry)
            .where(SourceRegistry.system_type == "confluence")
        )
        connectors = list(result.scalars().all())

        if not connectors:
            print("No confluence connectors found in database")
            return

        print(f"Found {len(connectors)} confluence connector(s)")
        print()

        for conn in connectors:
            print(f"  source_id: {conn.source_id}")
            print(f"  current base_url: {conn.base_url}")

            # Determine correct URL
            new_url = None

            # Check if it maps to Apache wiki
            if conn.source_id in CONFLUENCE_URL_MAP:
                new_url = CONFLUENCE_URL_MAP[conn.source_id]
            # Check if base_url is a mock domain
            elif any(m in (conn.base_url or "")
                     for m in MOCK_DOMAINS):
                new_url = ATLASSIAN_CORRECT_URL
            # Check if it is the HPE Atlassian instance
            elif "atlassian.net" in (conn.base_url or ""):
                new_url = ATLASSIAN_CORRECT_URL
            # Apache wiki
            elif "cwiki.apache.org" in (conn.base_url or ""):
                new_url = "https://cwiki.apache.org/confluence"

            if new_url and new_url != conn.base_url:
                await db.execute(
                    update(SourceRegistry)
                    .where(SourceRegistry.source_id == conn.source_id)
                    .values(base_url=new_url)
                )
                print(f"  FIXED → {new_url}")
            else:
                print(f"  OK — no change needed")
            print()

        await db.commit()
        print("All confluence base_urls updated.")
        print("Restart the backend to reload connectors.")


if __name__ == "__main__":
    asyncio.run(fix())
