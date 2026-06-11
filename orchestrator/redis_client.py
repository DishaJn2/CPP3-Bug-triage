import json
import os
import redis.asyncio as aioredis
import structlog
from dotenv import load_dotenv

from api_gateway.config import (
    REDIS_TTL_BUGLIST_SECONDS,
    REDIS_TTL_CASE_SECONDS,
    REDIS_TTL_PANEL_SECONDS,
    REDIS_TTL_TICKET_SECONDS,
)

load_dotenv()

log = structlog.get_logger()
_redis_client = None
PANEL_ORDER = [
    "bug_context",
    "related_issues",
    "linked_context",
    "knowledge_base",
    "ai_summary",
    "pipeline_done",
]


def buglist_cache_key(source_id: str, status: str, severity: str) -> str:
    severity_key = severity or "all"
    status_key = status or "open"
    return f"buglist:{source_id}:{status_key}:{severity_key}"


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(url, decode_responses=True)
    return _redis_client


async def cache_ticket(source_id: str, ticket_id: str, data: dict, ttl: int = REDIS_TTL_TICKET_SECONDS) -> None:
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


async def cache_buglist(source_id: str, status: str, severity: str, data: list, ttl: int = REDIS_TTL_BUGLIST_SECONDS) -> None:
    try:
        r = await get_redis()
        key = buglist_cache_key(source_id, status, severity)
        await r.setex(key, ttl, json.dumps(data))
    except Exception as e:
        log.warning("cache_buglist failed", error=str(e))


async def get_cached_buglist(source_id: str, status: str, severity: str) -> list | None:
    try:
        r = await get_redis()
        key = buglist_cache_key(source_id, status, severity)
        val = await r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def publish_panel_update(case_id: str, panel_name: str, data: dict) -> None:
    try:
        message = await store_panel_update(case_id, panel_name, data)
        r = await get_redis()
        await r.publish(f"ws:{case_id}", message)

        log.info("Panel published",
            case_id=case_id, panel=panel_name)

    except Exception as e:
        log.warning("publish_panel_update failed", error=str(e))


async def store_panel_update(
        case_id: str,
        panel_name: str,
        data: dict,
        agent: str = "",
        status: str = "completed") -> str:
    r = await get_redis()
    message = json.dumps({
        "panel": panel_name,
        "agent": agent,
        "status": status,
        "data": data,
    })
    await r.setex(
        f"panel:{case_id}:{panel_name}", REDIS_TTL_PANEL_SECONDS, message)
    existing = await r.lrange(f"panels:{case_id}", 0, -1)
    names = [
        item.decode() if isinstance(item, bytes) else item
        for item in existing
    ]
    if panel_name not in names:
        await r.rpush(f"panels:{case_id}", panel_name)
    await r.expire(f"panels:{case_id}", REDIS_TTL_PANEL_SECONDS)
    return message


async def publish_pipeline_done(
        case_id: str,
        status: str,
        duration_ms: int,
        severity: str = "",
        confidence: float | None = None,
        error: str = "") -> str:
    r = await get_redis()
    message = json.dumps({
        "type": "pipeline_done",
        "case_id": case_id,
        "status": status,
        "panels": [
            "bug_context",
            "related_issues",
            "knowledge_base",
            "ai_summary",
        ],
        "severity": severity,
        "confidence": confidence,
        "duration_ms": duration_ms,
        "error": error,
    })
    await r.setex(
        f"panel:{case_id}:pipeline_done", REDIS_TTL_PANEL_SECONDS, message)
    existing = await r.lrange(f"panels:{case_id}", 0, -1)
    names = [
        item.decode() if isinstance(item, bytes) else item
        for item in existing
    ]
    if "pipeline_done" not in names:
        await r.rpush(f"panels:{case_id}", "pipeline_done")
    await r.expire(f"panels:{case_id}", REDIS_TTL_PANEL_SECONDS)
    await r.publish(f"ws:{case_id}", message)
    return message


async def store_pipeline_complete(case_id: str, severity: str,
                                   confidence: float,
                                   duration_ms: int) -> None:
    try:
        await publish_pipeline_done(
            case_id=case_id,
            status="completed",
            severity=severity,
            confidence=confidence,
            duration_ms=duration_ms,
        )
    except Exception as e:
        log.warning("store_pipeline_complete failed", error=str(e))


async def get_stored_panels(case_id: str) -> list[dict]:
    """Get all panels already published for this case (for late WebSocket connections)."""
    try:
        r = await get_redis()
        panel_names = await r.lrange(f"panels:{case_id}", 0, -1)
        seen = set()
        panels = []
        names = [
            name.decode() if isinstance(name, bytes) else name
            for name in panel_names
        ]
        names.sort(key=lambda name: (
            PANEL_ORDER.index(name)
            if name in PANEL_ORDER else len(PANEL_ORDER)))
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            key = f"panel:{case_id}:{name}"
            val = await r.get(key)
            if val:
                panels.append(json.loads(val))
        return panels
    except Exception:
        return []


async def cache_case_result(case_id: str, data: dict, ttl: int = REDIS_TTL_CASE_SECONDS) -> None:
    try:
        r = await get_redis()
        await r.setex(f"case:{case_id}", ttl, json.dumps(data))
    except Exception as e:
        log.warning("cache_case_result failed", error=str(e))


async def purge_buglist_cache() -> int:
    try:
        r = await get_redis()
        keys = []
        for pattern in (
            "buglist:*",
            "bug_list:*",
            "bug:data:*",
            "buglist:all:scores",
            "buglist:last_refreshed",
        ):
            async for key in r.scan_iter(pattern):
                keys.append(key)
        keys = list(dict.fromkeys(keys))
        if keys:
            await r.delete(*keys)
        return len(keys)
    except Exception as e:
        log.warning("purge_buglist_cache failed", error=str(e))
        return 0


async def get_cached_case_result(case_id: str) -> dict | None:
    try:
        r = await get_redis()
        val = await r.get(f"case:{case_id}")
        return json.loads(val) if val else None
    except Exception:
        return None
