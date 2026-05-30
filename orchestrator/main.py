import asyncio
import os
import structlog
from dotenv import load_dotenv
from .kafka_consumer import consume_triage_requests

load_dotenv()
log = structlog.get_logger()


async def main():
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    log.info("Starting orchestrator", kafka=kafka_servers)
    await consume_triage_requests()


if __name__ == "__main__":
    asyncio.run(main())
