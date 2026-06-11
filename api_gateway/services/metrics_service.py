from datetime import datetime, timezone

from sqlalchemy import select

from orchestrator.connectors.registry import ConnectorRegistry
from orchestrator.db.models import AuditLog
from orchestrator.db.repositories.audit_log import (
    get_metrics_summary,
    list_recent_pipeline_completions,
)
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.redis_client import get_cached_buglist

_BUG_SOURCE_TYPES = {"github", "jira", "jira_apache", "bugzilla"}


async def get_metrics() -> dict:
    async with AsyncSessionLocal() as db:
        summary = await get_metrics_summary(db)
        recent  = await list_recent_pipeline_completions(
            db, limit=10)
        failed_result = await db.execute(
            select(AuditLog.id).where(AuditLog.status == "failed")
        )
        failed_triages = len(failed_result.scalars().all())

    all_connectors = await ConnectorRegistry.get_all_enabled()
    bug_connectors = [
        c for c in all_connectors
        if c.system_type in _BUG_SOURCE_TYPES
    ]

    by_severity: dict[str, int] = {
        "P0": 0, "P1": 0, "P2": 0, "P3": 0, "Unknown": 0}
    source_counts: dict[str, int] = {}
    total_confidence = 0.0
    confidence_count = 0

    for entry in recent:
        s = (
            (entry.summary or {}).get("unified_severity")
            or (entry.summary or {}).get("severity", "Unknown")
        )
        if s not in by_severity:
            s = "Unknown"
        by_severity[s] += 1
        src = entry.source_id or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
        conf = (entry.summary or {}).get("confidence", 0)
        if conf:
            total_confidence += conf
            confidence_count += 1

    avg_confidence = (
        round(total_confidence / confidence_count, 2)
        if confidence_count else 0)

    # Live P0/P1 counts from Redis-cached bug data
    live_p0 = 0
    live_p1 = 0
    live_total = 0
    try:
        for connector in bug_connectors:
            cached = await get_cached_buglist(
                connector.source_id, "open", "")
            if cached:
                for bug in cached:
                    live_total += 1
                    sev = bug.get("severity", "Unknown")
                    if sev == "P0":
                        live_p0 += 1
                    elif sev == "P1":
                        live_p1 += 1
    except Exception:
        pass

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    triaged_today = sum(
        1 for e in recent
        if e.created_at and e.created_at >= today_start
    )

    total_triages = summary.get("total_triaged", 0)
    needs_triage  = max(0, live_total - total_triages)

    return {
        "total_triages":   total_triages,
        "total_triaged":   total_triages,
        "sources_online":  len(bug_connectors),
        "sources_total":   len(bug_connectors),
        "by_severity":     by_severity,
        "by_source":       source_counts,
        "avg_confidence":  avg_confidence,
        "live_p0_count":   live_p0,
        "live_p1_count":   live_p1,
        "live_total_bugs": live_total,
        "triaged_today":   triaged_today,
        "needs_triage":    needs_triage,
        "failed_triages":  failed_triages,
        "recent_activity": [
            {
                "case_id":    e.case_id or "",
                "bug_id":     e.bug_id,
                "source_id":  e.source_id or "",
                "severity":   (
                    (e.summary or {}).get("unified_severity")
                    or (e.summary or {}).get(
                        "severity", "Unknown")),
                "confidence": (
                    (e.summary or {}).get("confidence", 0)),
                "root_cause": (
                    ((e.summary or {}).get(
                        "root_cause") or "")[:100]),
                "duration_ms": e.duration_ms or 0,
                "engineer_id": e.engineer_id or "",
                "created_at":  (
                    e.created_at.isoformat()
                    if e.created_at else ""),
            }
            for e in recent
        ],
    }
