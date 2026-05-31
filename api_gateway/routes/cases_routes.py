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


async def background_full_fetch(connector_list: list) -> None:
    """Fetch more pages per connector and warm Redis after the fast response is sent."""
    for connector in connector_list:
        try:
            existing = await get_cached_buglist(connector.source_id, "open", "")
            if existing and len(existing) > 50:
                continue  # already well-populated

            all_tickets = []
            if connector.system_type == "github":
                for pg in range(1, 6):
                    batch = await asyncio.wait_for(
                        connector.search("", max_results=100, page=pg),
                        timeout=12.0,
                    )
                    if not batch:
                        break
                    all_tickets.extend(batch)
                    if len(batch) < 100:
                        break
                    await asyncio.sleep(0.5)
            elif connector.system_type == "jira_apache":
                for start_at in range(0, 300, 50):
                    batch = await asyncio.wait_for(
                        connector.search("", max_results=50, start_at=start_at),
                        timeout=12.0,
                    )
                    if not batch:
                        break
                    all_tickets.extend(batch)
                    if len(batch) < 50:
                        break
                    await asyncio.sleep(0.5)
            elif connector.system_type == "bugzilla":
                for offset in range(0, 2000, 500):
                    batch = await asyncio.wait_for(
                        connector.search("", max_results=500, offset=offset),
                        timeout=15.0,
                    )
                    if not batch:
                        break
                    all_tickets.extend(batch)
                    if len(batch) < 500:
                        break
                    await asyncio.sleep(0.5)

            if all_tickets:
                data = [dataclasses.asdict(t) for t in all_tickets]
                await cache_buglist(connector.source_id, "open", "", data, ttl=300)
                print(f"[BackgroundFetch] {connector.source_id}: {len(data)} bugs cached", flush=True)
        except Exception as e:
            print(f"[BackgroundFetch] {connector.source_id} failed: {type(e).__name__}: {str(e)[:80]}", flush=True)


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

    if not connectors:
        return {
            "bugs": [], "total": 0, "page": page,
            "page_size": page_size, "sources_online": 0,
            "sources_total": 0, "partial": False,
            "message": "No connectors configured",
        }

    async def fetch_one(connector):
        try:
            cached = await get_cached_buglist(connector.source_id, "open", "")
            if cached is not None:
                return connector.source_id, cached, True

            tickets = []
            if connector.system_type == "github":
                for pg in range(1, 3):  # 2 pages × 100 = 200 bugs on cold cache
                    batch = await asyncio.wait_for(
                        connector.search("", max_results=100, page=pg),
                        timeout=15.0,
                    )
                    if not batch:
                        break
                    tickets.extend(batch)
                    if len(batch) < 100:
                        break
            elif connector.system_type == "jira_apache":
                for start_at in range(0, 100, 50):  # 2 pages × 50 = 100 bugs on cold cache
                    batch = await asyncio.wait_for(
                        connector.search("", max_results=50, start_at=start_at),
                        timeout=15.0,
                    )
                    if not batch:
                        break
                    tickets.extend(batch)
                    if len(batch) < 50:
                        break
            elif connector.system_type == "bugzilla":
                # Single fetch of 500 on cold cache; background task fills the rest
                tickets = list(await asyncio.wait_for(
                    connector.search("", max_results=500, offset=0),
                    timeout=20.0,
                ) or [])
            else:
                tickets = list(await asyncio.wait_for(
                    connector.search("", max_results=100),
                    timeout=15.0,
                ) or [])

            data = [dataclasses.asdict(t) for t in tickets]
            ttl = 300 if len(data) > 10 else 60
            await cache_buglist(connector.source_id, "open", "", data, ttl=ttl)
            return connector.source_id, data, False
        except Exception as e:
            print(f"[BugList] {connector.source_id} failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
            return connector.source_id, [], False

    tasks = {asyncio.create_task(fetch_one(c)): c.source_id for c in connectors}
    done, pending = await asyncio.wait(tasks.keys(), timeout=25.0)

    for task in pending:
        task.cancel()
        print(f"[BugList] Cancelled slow connector: {tasks[task]}", flush=True)

    all_bugs = []
    sources_online = 0
    for task in done:
        try:
            _, bugs, _ = task.result()
            all_bugs.extend(bugs)
            sources_online += 1
        except Exception:
            pass

    if search:
        sl = search.lower().strip()
        all_bugs = [
            b for b in all_bugs
            if sl in str(b.get("ticket_id", "")).lower()
            or sl in str(b.get("title", "")).lower()
            or sl in str(b.get("source_id", "")).lower()
            or str(b.get("ticket_id", "")).lower().endswith(sl)
            or str(b.get("ticket_id", "")).lower().startswith(sl)
        ]
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

    # Warm cache with more pages in the background after responding
    asyncio.create_task(background_full_fetch(connectors))

    return {
        "bugs": page_bugs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "sources_online": sources_online,
        "sources_total": len(connectors),
        "partial": len(pending) > 0,
    }


@router.post("/bugs/warm")
async def warm_bug_cache(user: User = Depends(get_current_user)):
    connectors = await ConnectorRegistry.get_all_enabled()
    asyncio.create_task(background_full_fetch(connectors))
    return {
        "status": "warming",
        "connectors": len(connectors),
        "message": f"Cache warming started for {len(connectors)} connectors in background",
    }


@router.post("/bugs/refresh")
async def refresh_bugs(user: User = Depends(get_current_user)):
    from orchestrator.redis_client import purge_buglist_cache
    cleared = await purge_buglist_cache()
    return {"cleared_keys": cleared, "message": "Bug list cache cleared. Next GET /bugs will fetch fresh data."}


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
        recent = await list_recent_pipeline_completions(db, limit=10)

    connectors = await ConnectorRegistry.get_all_enabled()

    severity_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "Unknown": 0}
    source_counts: dict[str, int] = {}
    total_confidence = 0.0
    confidence_count = 0

    for entry in recent:
        s = (entry.summary or {}).get("unified_severity") or (entry.summary or {}).get("severity", "Unknown")
        if s not in severity_counts:
            s = "Unknown"
        severity_counts[s] += 1
        src = entry.source_id or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
        conf = (entry.summary or {}).get("confidence", 0)
        if conf:
            total_confidence += conf
            confidence_count += 1

    avg_confidence = round(total_confidence / confidence_count, 2) if confidence_count else 0

    return {
        "total_triages": summary["total_triaged"],
        "total_triaged": summary["total_triaged"],
        "sources_online": len(connectors),
        "sources_total": len(connectors),
        "by_severity": severity_counts,
        "by_source": source_counts,
        "avg_confidence": avg_confidence,
        "recent_activity": [
            {
                "case_id":     e.case_id or "",
                "bug_id":      e.bug_id,
                "source_id":   e.source_id or "",
                "severity":    (e.summary or {}).get("unified_severity") or (e.summary or {}).get("severity", "Unknown"),
                "confidence":  (e.summary or {}).get("confidence", 0),
                "root_cause":  ((e.summary or {}).get("root_cause") or "")[:100],
                "duration_ms": e.duration_ms or 0,
                "engineer_id": e.engineer_id or "",
                "created_at":  e.created_at.isoformat() if e.created_at else "",
            }
            for e in recent
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
