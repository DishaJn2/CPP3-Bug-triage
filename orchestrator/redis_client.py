import json
import os
import redis.asyncio as aioredis
import structlog
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()
_redis_client = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(url, decode_responses=True)
    return _redis_client


async def cache_ticket(source_id: str, ticket_id: str, data: dict, ttl: int = 300) -> None:
    try:
        r = await get_redis()
        key = f"ticket:{source_id}:{ticket_id}"
        await r.setex(key, ttl, json.dumps(data))
    except Exception as e:
        log.warning("cache_ticket failed", error=str(e))


async def get_cached_ticket(source_id: str, ticket_id: str) -> dict | None:
    try:
        r = await get_redis()
        key = f"ticket:{source_id}:{ticket_id}"
        val = await r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def cache_buglist(source_id: str, status: str, severity: str, data: list, ttl: int = 120) -> None:
    try:
        r = await get_redis()
        key = f"buglist:{source_id}:{status}:{severity}"
        await r.setex(key, ttl, json.dumps(data))
    except Exception as e:
        log.warning("cache_buglist failed", error=str(e))


async def get_cached_buglist(source_id: str, status: str, severity: str) -> list | None:
    try:
        r = await get_redis()
        key = f"buglist:{source_id}:{status}:{severity}"
        val = await r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def publish_panel_update(case_id: str, panel_name: str, data: dict) -> None:
    try:
        r = await get_redis()
        message = json.dumps({"panel": panel_name, "data": data})
        await r.publish(f"ws:{case_id}", message)
    except Exception as e:
        log.warning("publish_panel_update failed", error=str(e))


async def cache_case_result(case_id: str, data: dict, ttl: int = 3600) -> None:
    try:
        r = await get_redis()
        await r.setex(f"case:{case_id}", ttl, json.dumps(data))
    except Exception as e:
        log.warning("cache_case_result failed", error=str(e))


async def get_cached_case_result(case_id: str) -> dict | None:
    try:
        r = await get_redis()
        val = await r.get(f"case:{case_id}")
        return json.loads(val) if val else None
    except Exception:
        return None
