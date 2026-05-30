import asyncio
import dataclasses
import time
from fastapi import APIRouter, Depends, Query
from ..auth import get_current_user, User
from orchestrator.connectors.registry import ConnectorRegistry
from orchestrator.redis_client import get_cached_buglist, cache_buglist
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.repositories.audit_log import (
    get_last_triage_for_bug, get_metrics_summary, list_recent_pipeline_completions,
)

router = APIRouter(tags=["cases"])

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Unknown": 4}


@router.get("/debug/sources")
async def debug_sources():
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.repositories.source_registry import get_all_sources
    from orchestrator.connectors.registry import ConnectorRegistry, load_connectors_from_db
    import os

    async with AsyncSessionLocal() as db:
        sources = await get_all_sources(db)

    connectors = await load_connectors_from_db()

    return {
        "db_sources": [
            {
                "source_id": s.source_id,
                "system_type": s.system_type,
                "enabled": s.enabled,
                "auth_secret_ref": s.auth_secret_ref,
                "token_present": bool(os.environ.get(s.auth_secret_ref or "", "")),
                "project_key": s.project_key,
            }
            for s in sources
        ],
        "connectors_loaded": len(connectors),
        "connector_ids": [c.source_id for c in connectors],
    }


@router.get("/bugs")
async def get_bugs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    severity: str = Query(""),
    source: str = Query(""),
    status: str = Query(""),
    user: User = Depends(get_current_user),
):
    connectors = await ConnectorRegistry.get_all_enabled()

    async def fetch_all_for_connector(connector):
        cached = await get_cached_buglist(connector.source_id, "open", "")
        if cached is not None:
            return connector.source_id, cached, True

        all_tickets = []

        if connector.system_type == "github":
            for pg in range(1, 11):
                batch = await connector.search("", max_results=100, page=pg)
                if not batch:
                    break
                all_tickets.extend(batch)
                if len(batch) < 100:
                    break

        elif connector.system_type == "jira_apache":
            for start in range(0, 1000, 50):
                batch = await connector.search("", max_results=50, start_at=start)
                if not batch:
                    break
                all_tickets.extend(batch)
                if len(batch) < 50:
                    break

        elif connector.system_type == "bugzilla":
            for offset in range(0, 2500, 500):
                batch = await connector.search("", max_results=500, offset=offset)
                if not batch:
                    break
                all_tickets.extend(batch)
                if len(batch) < 500:
                    break

        else:
            all_tickets = await connector.search("", max_results=100)

        data = [dataclasses.asdict(t) for t in all_tickets]
        await cache_buglist(connector.source_id, "open", "", data, ttl=120)
        return connector.source_id, data, False

    tasks = [fetch_all_for_connector(c) for c in connectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_bugs = []
    sources_online = 0
    for res in results:
        if isinstance(res, Exception):
            continue
        _, bugs, _ = res
        all_bugs.extend(bugs)
        sources_online += 1

    if search:
        sl = search.lower()
        all_bugs = [b for b in all_bugs if sl in b.get("title", "").lower() or sl in b.get("ticket_id", "").lower()]
    if severity:
        all_bugs = [b for b in all_bugs if b.get("severity", "") == severity]
    if source:
        all_bugs = [b for b in all_bugs if b.get("source_id", "") == source]
    if status:
        all_bugs = [b for b in all_bugs if b.get("status", "").lower() == status.lower()]

    all_bugs.sort(key=lambda b: SEVERITY_ORDER.get(b.get("severity", "Unknown"), 4))
    total = len(all_bugs)
    start_idx = (page - 1) * page_size
    page_bugs = all_bugs[start_idx: start_idx + page_size]

    return {"bugs": page_bugs, "total": total, "page": page,
            "page_size": page_size, "sources_online": sources_online}


@router.get("/bugs/{bug_id}/status")
async def get_bug_status(bug_id: str, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        last_triage = await get_last_triage_for_bug(db, bug_id)

    if not last_triage:
        return {
            "is_new": True,
            "needs_retriage": True,
            "changes": [],
            "last_triaged_at": None,
            "last_severity": None,
            "last_confidence": None,
        }

    summary = last_triage.summary or {}
    last_severity = summary.get("severity") or summary.get("unified_severity")
    last_status = summary.get("status", "")
    last_updated_at = summary.get("updated_at", "")
    last_confidence = summary.get("confidence", 0)
    last_triaged_at = last_triage.created_at.isoformat() if last_triage.created_at else None

    changes = []
    needs_retriage = False

    try:
        connectors = await ConnectorRegistry.get_all_enabled()
        source_id = last_triage.source_id or ""
        connector = None

        if source_id:
            for c in connectors:
                if c.source_id == source_id:
                    connector = c
                    break

        if not connector:
            for c in connectors:
                if bug_id.upper().startswith(c.ticket_prefix.upper()):
                    connector = c
                    break

        if connector:
            current = await asyncio.wait_for(connector.get(bug_id), timeout=8.0)
            if current:
                if current.updated_at and last_updated_at:
                    if str(current.updated_at) > str(last_updated_at):
                        changes.append("Bug updated since last triage")
                        needs_retriage = True

                current_sev = current.severity or "Unknown"
                if last_severity and current_sev != last_severity:
                    changes.append(f"Severity changed: {last_severity} → {current_sev}")
                    needs_retriage = True

                if last_status and current.status != last_status:
                    changes.append(f"Status changed: {last_status} → {current.status}")
                    needs_retriage = True
    except Exception:
        changes.append("Could not fetch current state from external system")

    return {
        "is_new": False,
        "needs_retriage": needs_retriage,
        "changes": changes,
        "last_triaged_at": last_triaged_at,
        "last_severity": last_severity,
        "last_confidence": last_confidence,
        "case_id": last_triage.case_id or "",
    }


@router.get("/metrics")
async def get_metrics(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        summary = await get_metrics_summary(db)
        recent = await list_recent_pipeline_completions(db, limit=100)

    connectors = await ConnectorRegistry.get_all_enabled()

    severity_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "Unknown": 0}
    source_counts: dict[str, int] = {}
    for entry in recent:
        s = (entry.summary or {}).get("unified_severity") or (entry.summary or {}).get("severity", "Unknown")
        if s not in severity_counts:
            s = "Unknown"
        severity_counts[s] += 1
        src = entry.source_id or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1

    recent4 = recent[:4]

    return {
        "total_triaged": summary["total_triaged"],
        "total_triages": summary["total_triaged"],
        "sources_online": len(connectors),
        "by_severity": severity_counts,
        "by_source": source_counts,
        "recent_activity": [
            {
                "case_id":     e.case_id,
                "bug_id":      e.bug_id,
                "source_id":   e.source_id or "",
                "severity":    (e.summary or {}).get("unified_severity") or (e.summary or {}).get("severity", "Unknown"),
                "confidence":  (e.summary or {}).get("confidence", 0),
                "duration_ms": e.duration_ms,
                "engineer_id": e.engineer_id,
                "created_at":  e.created_at.isoformat() if e.created_at else "",
            }
            for e in recent4
        ],
    }


@router.get("/history/triage")
async def get_triage_history(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        entries = await list_recent_pipeline_completions(db, limit=limit)

    results = []
    for e in entries:
        summary = e.summary or {}
        results.append({
            "id": e.id,
            "case_id": e.case_id or "",
            "bug_id": e.bug_id,
            "source_id": e.source_id or "",
            "engineer_id": e.engineer_id or "",
            "severity": summary.get("severity") or summary.get("unified_severity", "Unknown"),
            "confidence": summary.get("confidence", 0),
            "root_cause": (summary.get("root_cause") or "")[:120],
            "duration_ms": e.duration_ms or 0,
            "systems_queried": e.systems_queried or [],
            "triaged_at": e.created_at.isoformat() if e.created_at else None,
        })
    return results


@router.get("/cases/{case_id}")
async def get_case_result(
    case_id: str,
    user: User = Depends(get_current_user),
):
    from fastapi import HTTPException
    from orchestrator.redis_client import get_cached_case_result
    cached = await get_cached_case_result(case_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="Case result not found. Results are cached for 1 hour after triage.",
        )
    return cached
