import asyncio
import dataclasses
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth import get_current_user, User
from orchestrator.connectors.registry import ConnectorRegistry
from orchestrator.redis_client import get_cached_buglist, cache_buglist
from orchestrator.utils.url_utils import sanitize_bug_url
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.models import (
    AuditLog, SystemGroupRegistry, BugGroupMapping,
)
from orchestrator.db.repositories.audit_log import (
    get_last_triage_for_bug, get_metrics_summary,
    list_recent_pipeline_completions,
)
from ..services import bug_service, case_service, metrics_service
router = APIRouter(tags=["cases"])
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Unknown": 4}
_BUG_SOURCE_TYPES = {"github", "jira", "jira_apache", "bugzilla"}


# ── Group assembly ────────────────────────────────────────────────

async def assemble_grouped_bug_list(
        raw_bugs: list[dict],
        db: AsyncSession) -> dict:
    """
    Transform a flat bug page into a tree of groups + standalones.
    All DB lookups are single IN-queries — no N+1 queries.
    """
    all_ticket_ids: set[str] = {
        b["ticket_id"] for b in raw_bugs if b.get("ticket_id")
    }
    live_by_ticket = {
        b["ticket_id"]: b for b in raw_bugs if b.get("ticket_id")
    }

    # Step 2: batch group-mapping lookup
    group_map: dict[str, str] = {}        # raw_ticket_id → group_id
    if all_ticket_ids:
        result = await db.execute(
            select(
                BugGroupMapping.raw_ticket_id,
                BugGroupMapping.group_id,
            ).where(BugGroupMapping.raw_ticket_id.in_(
                list(all_ticket_ids)))
        )
        for row in result.all():
            group_map[row.raw_ticket_id] = row.group_id

    # Step 3: batch group-info lookup
    group_info: dict[str, dict] = {}      # group_id → metadata
    group_ids = set(group_map.values())
    if group_ids:
        result = await db.execute(
            select(SystemGroupRegistry).where(
                SystemGroupRegistry.group_id.in_(
                    list(group_ids)))
        )
        for grp in result.scalars().all():
            group_info[grp.group_id] = {
                "priority":  grp.priority or "Unknown",
                "status":    grp.status   or "active",
                "title":     grp.title    or "",
                "created_at": (
                    grp.created_at.isoformat()
                    if grp.created_at else ""),
            }

    # Step 4: expand all group mappings for groups touched by this page
    group_members: dict[str, list] = defaultdict(list)
    if group_ids:
        result = await db.execute(
            select(BugGroupMapping).where(
                BugGroupMapping.group_id.in_(list(group_ids)))
        )
        for mapping in result.scalars().all():
            group_members[mapping.group_id].append(mapping)

    expanded_ticket_ids = set(all_ticket_ids)
    for members in group_members.values():
        for member in members:
            if member.raw_ticket_id:
                expanded_ticket_ids.add(member.raw_ticket_id)

    # Step 5: batch triage-info lookup
    triage_map: dict[str, dict] = {}
    if expanded_ticket_ids:
        result = await db.execute(
            select(AuditLog)
            .where(
                AuditLog.bug_id.in_(list(expanded_ticket_ids)),
                AuditLog.step == "pipeline_complete",
            )
            .order_by(AuditLog.bug_id, desc(AuditLog.created_at))
        )
        seen: set[str] = set()
        for entry in result.scalars().all():
            if entry.bug_id not in seen:
                seen.add(entry.bug_id)
                triage_map[entry.bug_id] = {
                    "case_id":   entry.case_id or "",
                    "severity":  (
                        (entry.summary or {}).get("severity")
                        or (entry.summary or {}).get(
                            "unified_severity", "")),
                    "confidence": (
                        (entry.summary or {}).get(
                            "confidence", 0)),
                    "triaged_at": (
                        entry.created_at.isoformat()
                        if entry.created_at else ""),
                    "systems_queried": (
                        entry.systems_queried or []),
                    "duration_ms": entry.duration_ms or 0,
                }

    def member_to_bug(member: BugGroupMapping) -> dict:
        live = live_by_ticket.get(member.raw_ticket_id, {})
        return {
            "ticket_id": member.raw_ticket_id,
            "source": (
                live.get("source")
                or member.system_type
                or member.source_id),
            "source_id": member.source_id,
            "system_type": (
                live.get("system_type")
                or member.system_type
                or member.source_id),
            "source_display_name": live.get(
                "source_display_name", member.source_id),
            "title": live.get("title") or member.title or "",
            "severity": (
                live.get("severity")
                or member.severity
                or "Unknown"),
            "status": live.get("status") or member.status or "open",
            "assignee": live.get("assignee", ""),
            "updated_at": live.get("updated_at", ""),
            "url": live.get("url") or member.url or "",
            "similarity_score": member.similarity_score,
            "similarity_label": member.similarity_label or "",
            "similarity_reason": member.similarity_reason or "",
            "role": member.role or "child",
            "triage_info": triage_map.get(member.raw_ticket_id),
            "is_triaged": member.raw_ticket_id in triage_map,
        }

    # Step 6: split grouped vs. ungrouped
    ungrouped_bugs = [
        b for b in raw_bugs
        if b.get("ticket_id", "") not in group_map
    ]

    # Step 7: build explicit group root + child rows
    _PRIO = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Unknown": 4}
    group_rows = []
    for gid, members in group_members.items():
        info = group_info.get(gid, {})
        member_rows = [member_to_bug(member) for member in members]
        root = next(
            (row for row in member_rows if row.get("role") == "root"),
            member_rows[0] if member_rows else None,
        )
        if not root:
            continue
        child_rows = [
            row for row in member_rows
            if row.get("ticket_id") != root.get("ticket_id")
        ]
        group_rows.append({
            "group_id":   gid,
            "type":       "group",
            "priority":   (
                info.get("priority")
                or root.get("severity")
                or "Unknown"),
            "status":     info.get("status", "active"),
            "title":      info.get("title") or root.get("title", ""),
            "created_at": info.get("created_at", ""),
            "child_count": len(child_rows),
            "root":       root,
            "children":   child_rows,
            "triage_info": root.get("triage_info"),
        })
    group_rows.sort(key=lambda g: (
        _PRIO.get(g["priority"], 4),
        g["created_at"],
    ))

    # Step 7: build standalone rows
    standalone_rows = []
    for bug in ungrouped_bugs:
        tid = bug.get("ticket_id", "")
        b   = dict(bug)
        b["type"]       = "standalone"
        b["is_triaged"] = tid in triage_map
        b["triage_info"] = triage_map.get(tid)
        standalone_rows.append(b)

    return {"ungrouped": standalone_rows, "groups": group_rows}


# ── Background helpers ────────────────────────────────────────────

async def background_full_fetch(connector_list: list) -> None:
    for connector in connector_list:
        if connector.system_type not in _BUG_SOURCE_TYPES:
            continue
        try:
            existing = await get_cached_buglist(
                connector.source_id, "open", "")
            if existing and len(existing) > 50:
                continue

            all_tickets = await asyncio.wait_for(
                connector.search_open_bugs(
                    status="open",
                    severity="",
                    max_results=300,
                ),
                timeout=20.0,
            )

            if all_tickets:
                data = [
                    _normalize_list_bug(ticket, connector)
                    for ticket in all_tickets
                ]
                await cache_buglist(
                    connector.source_id, "open", "",
                    data, ttl=120)
                print(
                    f"[BackgroundFetch] {connector.source_id}: "
                    f"{len(data)} bugs cached", flush=True)
        except Exception as e:
            print(
                f"[BackgroundFetch] {connector.source_id} "
                f"failed: {type(e).__name__}: {str(e)[:80]}",
                flush=True)


@router.get("/debug/confluence-test")
async def debug_confluence(q: str = "NormalizeCTEIds"):
    import asyncio
    from orchestrator.connectors.registry import ConnectorRegistry

    connectors = await ConnectorRegistry.get_all_enabled()
    conf = next(
        (c for c in connectors if c.system_type == "confluence"),
        None)

    if not conf:
        return {"error": "No confluence connector found"}

    try:
        results = await asyncio.wait_for(
            conf.search(q, max_results=5), timeout=15.0)
        return {
            "connector":     conf.source_id,
            "base_url":      conf.base_url,
            "query":         q,
            "results_count": len(results),
            "titles":        [r.title for r in results],
            "urls":          [r.url for r in results],
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/debug/sources")
async def debug_sources():
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.repositories.source_registry import (
        get_all_sources)
    from orchestrator.connectors.registry import (
        ConnectorRegistry, load_connectors_from_db)
    import os

    async with AsyncSessionLocal() as db:
        sources = await get_all_sources(db)

    connectors = await load_connectors_from_db()

    return {
        "db_sources": [
            {
                "source_id":      s.source_id,
                "system_type":    s.system_type,
                "enabled":        s.enabled,
                "auth_secret_ref": s.auth_secret_ref,
                "token_present":  bool(
                    os.environ.get(s.auth_secret_ref or "", "")),
                "project_key":    s.project_key,
            }
            for s in sources
        ],
        "connectors_loaded": len(connectors),
        "connector_ids": [c.source_id for c in connectors],
    }


def get_bug_score(severity: str, updated_at: str) -> float:
    sev_val = {
        "P0": 4, "P1": 3, "P2": 2, "P3": 1
    }.get(severity or "Unknown", 0)
    ts = 0.0
    if updated_at:
        try:
            s = str(updated_at).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            if len(s) > 5 and s[-5] in ('+', '-'):
                s = s[:-2] + ":" + s[-2:]
            dt = datetime.fromisoformat(s)
            ts = dt.timestamp()
        except Exception:
            pass
    return sev_val * 10 + (ts / 2000000000.0)


def _normalize_list_bug(ticket, connector) -> dict:
    if dataclasses.is_dataclass(ticket):
        data = dataclasses.asdict(ticket)
    elif isinstance(ticket, dict):
        data = dict(ticket)
    else:
        data = {
            "ticket_id": getattr(ticket, "ticket_id", ""),
            "title": getattr(ticket, "title", ""),
            "severity": getattr(ticket, "severity", ""),
            "status": getattr(ticket, "status", ""),
            "assignee": getattr(ticket, "assignee", ""),
            "updated_at": getattr(ticket, "updated_at", ""),
            "url": getattr(ticket, "url", ""),
        }

    ticket_id = data.get("ticket_id") or data.get("id") or ""
    system_type = data.get("system_type") or connector.system_type
    source_id = data.get("source_id") or connector.source_id
    base_url = getattr(connector, "base_url", "")
    return {
        "ticket_id": ticket_id,
        "source": system_type,
        "source_id": source_id,
        "system_type": system_type,
        "source_display_name": getattr(
            connector, "display_name", connector.source_id),
        "title": data.get("title", ""),
        "severity": data.get("severity") or "Unknown",
        "status": data.get("status") or "open",
        "assignee": data.get("assignee", ""),
        "updated_at": data.get("updated_at", ""),
        "url": sanitize_bug_url(
            url=data.get("url", ""),
            system_type=system_type,
            bug_id=ticket_id,
            base_url=base_url,
        ),
    }


_FETCH_LOCKS = {}

async def _fetch_buglist_for_connector(
        connector,
        status: str,
        severity: str,
        max_results: int) -> dict:
    
    lock_key = f"{connector.source_id}:{status}:{severity}"
    if lock_key not in _FETCH_LOCKS:
        _FETCH_LOCKS[lock_key] = asyncio.Lock()
        
    async with _FETCH_LOCKS[lock_key]:
        # Check cache inside the lock to prevent stampede
        cached = await get_cached_buglist(
            connector.source_id, status, severity)
        if cached is not None:
            return {
                "source_id": connector.source_id,
                "bugs": cached,
                "cache_status": "hit",
                "error": None,
            }

        try:
            tickets = await asyncio.wait_for(
                connector.search_open_bugs(
                    status=status,
                    severity=severity,
                    max_results=max_results,
                ),
                timeout=90.0,
            )
            bugs = [
                _normalize_list_bug(ticket, connector)
                for ticket in (tickets or [])
            ]
            await cache_buglist(
                connector.source_id, status, severity, bugs, ttl=300)
            return {
                "source_id": connector.source_id,
                "bugs": bugs,
                "cache_status": "miss",
                "error": None,
            }
        except Exception as e:
            return {
                "source_id": connector.source_id,
                "bugs": [],
                "cache_status": "error",
                "error": {
                    "source_id": connector.source_id,
                    "system_type": connector.system_type,
                    "message": str(e)[:300],
                },
            }


async def _background_fetch_connector(connector) -> None:
    try:
        tickets = await asyncio.wait_for(
            connector.search_open_bugs(
                status="open",
                severity="",
                max_results=300,
            ),
            timeout=90.0,
        )

        if tickets:
            sanitized_data = [
                _normalize_list_bug(ticket, connector)
                for ticket in tickets
            ]

            await cache_buglist(
                connector.source_id, "open", "",
                sanitized_data, ttl=300)

            print(f"[BugList] {connector.source_id}: "
                  f"{len(sanitized_data)} bugs cached")

    except Exception as e:
        print(f"[BugList] {connector.source_id} "
              f"background fetch error: {e}")


# ── GET /bugs ─────────────────────────────────────────────────────

@router.get("/bugs")
async def get_bugs(
    page:       int = Query(1, ge=1),
    page_size:  int = Query(50, ge=1, le=200),
    search:     str = Query(""),
    severity:   str = Query(""),
    source:     str = Query(""),
    status:     str = Query(""),
    sort_field: str = Query("severity"),
    sort_order: str = Query("desc"),
    user: User = Depends(get_current_user),
):
    return await bug_service.get_bugs(
        page=page,
        page_size=page_size,
        search=search,
        severity=severity,
        source=source,
        status=status,
        sort_field=sort_field,
        sort_order=sort_order,
    )


# ── ORIGINAL FAT ROUTE (kept until confirmed working) ─────────────
# @router.get("/bugs")
# async def get_bugs(
#     page:       int = Query(1, ge=1),
#     page_size:  int = Query(50, ge=1, le=200),
#     search:     str = Query(""),
#     severity:   str = Query(""),
#     source:     str = Query(""),
#     status:     str = Query(""),
#     sort_field: str = Query("severity"),
#     sort_order: str = Query("desc"),
#     user: User = Depends(get_current_user),
# ):
#     all_connectors = await ConnectorRegistry.get_all_enabled()
#     connectors = [
#         c for c in all_connectors
#         if c.system_type in _BUG_SOURCE_TYPES
#     ]
#     if source:
#         connectors = [
#             c for c in connectors
#             if c.source_id == source or c.system_type == source
#         ]
#
#     if not connectors:
#         return {
#             "ungrouped": [], "groups": [],
#             "total": 0, "page": page,
#             "page_size": page_size, "sources_online": 0,
#             "sources_total": 0, "partial": False,
#             "bugs": [],
#             "source_errors": [],
#             "message": "No connectors configured",
#         }
#
#     fetch_status = status or "open"
#     fetch_severity = severity or ""
#     max_results = max(page * page_size, 100)
#     fetch_results = await asyncio.gather(
#         *[
#             _fetch_buglist_for_connector(
#                 connector=c,
#                 status=fetch_status,
#                 severity=fetch_severity,
#                 max_results=max_results,
#             )
#             for c in connectors
#         ],
#         return_exceptions=True,
#     )
#
#     all_bugs = []
#     source_errors = []
#     cache_statuses = []
#     for connector, result in zip(connectors, fetch_results):
#         if isinstance(result, Exception):
#             source_errors.append({
#                 "source_id": connector.source_id,
#                 "system_type": connector.system_type,
#                 "message": str(result)[:300],
#             })
#             continue
#
#         all_bugs.extend(result.get("bugs") or [])
#         cache_statuses.append(result.get("cache_status", "miss"))
#         if result.get("error"):
#             source_errors.append(result["error"])
#
#     sources_online = len(connectors) - len(source_errors)
#
#     # Filters
#     if search:
#         sl = search.strip().lower()
#
#         def matches(b: dict) -> bool:
#             if sl in (b.get("ticket_id") or "").lower():
#                 return True
#             if sl in (b.get("title") or "").lower():
#                 return True
#             if sl in (b.get("component") or "").lower():
#                 return True
#             if sl in (b.get("source_id") or "").lower():
#                 return True
#             if sl in (b.get("source_display_name") or "").lower():
#                 return True
#             if sl in (b.get("system_type") or "").lower():
#                 return True
#             if sl in (b.get("severity") or "").lower():
#                 return True
#             if sl in (b.get("status") or "").lower():
#                 return True
#             desc = (b.get("description") or "")[:200].lower()
#             if sl in desc:
#                 return True
#             for label in (b.get("labels") or []):
#                 if sl in str(label).lower():
#                     return True
#             return False
#
#         all_bugs = [b for b in all_bugs if matches(b)]
#     if severity:
#         all_bugs = [
#             b for b in all_bugs
#             if b.get("severity", "") == severity
#         ]
#     if status:
#         all_bugs = [
#             b for b in all_bugs
#             if b.get("status", "").lower() == status.lower()
#         ]
#
#     all_bugs.sort(
#         key=lambda b: SEVERITY_ORDER.get(
#             b.get("severity", "Unknown"), 4))
#     total     = len(all_bugs)
#     start_idx = (page - 1) * page_size
#     page_bugs = all_bugs[start_idx: start_idx + page_size]
#
#     # Assemble grouped tree (all DB lookups are IN-queries)
#     assembled: dict = {"ungrouped": [], "groups": []}
#     try:
#         async with AsyncSessionLocal() as db:
#             assembled = await assemble_grouped_bug_list(
#                 raw_bugs=page_bugs, db=db)
#     except Exception as e:
#         print(f"[BugList] assemble_grouped_bug_list failed: {e}",
#               flush=True)
#         for bug in page_bugs:
#             bug["type"]       = "standalone"
#             bug["is_triaged"] = False
#             bug["triage_info"] = None
#         assembled = {"ungrouped": page_bugs, "groups": []}
#
#     # Build flat bugs list for frontend (ungrouped + group root/children)
#     flat_bugs = assembled.get("ungrouped", []) + [
#         item
#         for group in assembled.get("groups", [])
#         for item in ([group.get("root")] + group.get("children", []))
#         if item
#     ]
#
#     if not cache_statuses:
#         cache_status = "error"
#     elif all(s == "hit" for s in cache_statuses):
#         cache_status = "hit"
#     elif any(s == "hit" for s in cache_statuses):
#         cache_status = "partial"
#     else:
#         cache_status = "miss"
#
#     response = {
#         **assembled,
#         "bugs":          flat_bugs,
#         "total":         total,
#         "page":          page,
#         "page_size":     page_size,
#         "sources_online": sources_online,
#         "sources_total": len(connectors),
#         "partial":       bool(source_errors),
#         "source_errors": source_errors,
#         "cache_status":  cache_status,
#         "cached_at":     time.time(),
#     }
#
#     return response


@router.post("/bugs/warm")
async def warm_bug_cache(user: User = Depends(get_current_user)):
    connectors = await ConnectorRegistry.get_all_enabled()
    asyncio.create_task(background_full_fetch(connectors))
    return {
        "status":  "warming",
        "connectors": len(connectors),
        "message": (
            f"Cache warming started for {len(connectors)} "
            f"connectors in background"),
    }


@router.post("/bugs/refresh")
async def refresh_bugs(user: User = Depends(get_current_user)):
    from orchestrator.redis_client import purge_buglist_cache
    cleared = await purge_buglist_cache()
    return {
        "cleared_keys": cleared,
        "message": (
            "Bug list cache cleared. "
            "Next GET /bugs will fetch fresh data."),
    }


@router.get("/bugs/{bug_id}/status")
async def get_bug_status(
    bug_id: str,
    user: User = Depends(get_current_user),
):
    return await bug_service.get_bug_status(bug_id)


# ── ORIGINAL FAT ROUTE (kept until confirmed working) ─────────────
# @router.get("/bugs/{bug_id}/status")
# async def get_bug_status(
#     bug_id: str,
#     user: User = Depends(get_current_user),
# ):
#     # Step 1: Fetch last audit record
#     async with AsyncSessionLocal() as db:
#         last_triage = await get_last_triage_for_bug(db, bug_id)
#
#     if not last_triage:
#         return {
#             "is_new":           True,
#             "needs_retriage":   True,
#             "changes":          [],
#             "last_triaged_at":  None,
#             "last_severity":    None,
#             "last_confidence":  None,
#         }
#
#     summary           = last_triage.summary or {}
#     ticket_updated_at = summary.get("ticket_updated_at") or summary.get("updated_at", "")
#     last_severity     = summary.get("ticket_severity") or summary.get("severity", "")
#     last_status       = summary.get("ticket_status") or summary.get("status", "")
#     ai_severity       = summary.get("ai_severity") or summary.get("severity", "")
#     root_cause        = summary.get("root_cause", "")
#     last_confidence   = summary.get("confidence", 0)
#     last_triaged_at   = (
#         last_triage.created_at.isoformat()
#         if last_triage.created_at else None
#     )
#
#     # Step 1b: Resolve connector
#     connector = None
#     try:
#         connector = await ConnectorRegistry.get_connector(
#             last_triage.source_id or "")
#     except Exception:
#         pass
#
#     if not connector:
#         try:
#             connectors  = await ConnectorRegistry.get_all_enabled()
#             bug_upper   = bug_id.upper()
#             sorted_c    = sorted(
#                 connectors,
#                 key=lambda c: len(c.ticket_prefix or ""),
#                 reverse=True)
#             for c in sorted_c:
#                 prefix = (c.ticket_prefix or "").upper().strip()
#                 if prefix and bug_upper.startswith(prefix):
#                     connector = c
#                     break
#         except Exception:
#             pass
#
#     if not connector:
#         return {
#             "is_new":           False,
#             "last_triaged_at":  last_triaged_at,
#             "last_severity":    last_severity,
#             "last_ai_severity": ai_severity,
#             "last_confidence":  last_confidence,
#             "root_cause":       root_cause,
#             "case_id":          last_triage.case_id,
#             "changes":          [],
#             "needs_retriage":   None,
#         }
#
#     # Step 2: Lightweight freshness check
#     live = {}
#     try:
#         live = await asyncio.wait_for(
#             connector.get_lightweight(bug_id),
#             timeout=8.0)
#     except Exception as e:
#         import structlog
#         structlog.get_logger().warning(
#             "get_lightweight failed",
#             bug_id=bug_id, error=str(e))
#
#     if not live:
#         return {
#             "is_new":           False,
#             "last_triaged_at":  last_triaged_at,
#             "last_severity":    last_severity,
#             "last_ai_severity": ai_severity,
#             "last_confidence":  last_confidence,
#             "root_cause":       root_cause,
#             "case_id":          last_triage.case_id,
#             "changes":          [],
#             "needs_retriage":   False,
#         }
#
#     # Step 3: Decide path
#     live_updated_at = live.get("updated_at", "")
#     live_severity   = live.get("severity", "")
#     live_status     = live.get("status", "")
#
#     def to_datetime(val) -> datetime:
#         if isinstance(val, datetime):
#             return val
#         if not val:
#             return datetime.min.replace(tzinfo=timezone.utc)
#         try:
#             s = str(val).strip()
#             if s.endswith("Z"):
#                 s = s[:-1] + "+00:00"
#             if len(s) > 5 and s[-5] in ('+', '-'):
#                 s = s[:-2] + ":" + s[-2:]
#             dt = datetime.fromisoformat(s)
#             if dt.tzinfo is None:
#                 dt = dt.replace(tzinfo=timezone.utc)
#             return dt
#         except Exception:
#             return datetime.min.replace(tzinfo=timezone.utc)
#
#     last_triaged_dt = to_datetime(last_triage.created_at)
#     live_updated_dt = to_datetime(live_updated_at)
#
#     no_change = (
#         live_updated_dt <= last_triaged_dt
#         and live_severity == last_severity
#         and live_status   == last_status
#     )
#
#     if no_change:
#         return {
#             "is_new":           False,
#             "last_triaged_at":  last_triaged_at,
#             "last_severity":    last_severity,
#             "last_ai_severity": ai_severity,
#             "last_confidence":  last_confidence,
#             "root_cause":       root_cause,
#             "case_id":          last_triage.case_id,
#             "changes":          [],
#             "needs_retriage":   False,
#         }
#
#     # Step 4: Change detected — fetch detailed changelog
#     changelog = []
#     try:
#         changelog = await asyncio.wait_for(
#             connector.get_changelog(
#                 bug_id, since=last_triaged_at),
#             timeout=10.0)
#     except Exception:
#         pass
#
#     # Step 5: Filter and build response
#     relevant = {
#         "priority", "status", "severity",
#         "assignee", "resolution", "description"
#     }
#     changes = [
#         {
#             "field":      e.field,
#             "from":       e.old_value,
#             "to":         e.new_value,
#             "changed_at": e.changed_at,
#             "changed_by": e.changed_by,
#         }
#         for e in changelog
#         if e.field.lower() in relevant
#     ]
#
#     if not changes:
#         if live_severity and live_severity != last_severity:
#             changes.append({
#                 "field":      "severity",
#                 "from":       last_severity,
#                 "to":         live_severity,
#                 "changed_at": live_updated_at,
#                 "changed_by": "",
#             })
#         if live_status and live_status != last_status:
#             changes.append({
#                 "field":      "status",
#                 "from":       last_status,
#                 "to":         live_status,
#                 "changed_at": live_updated_at,
#                 "changed_by": "",
#             })
#
#     return {
#         "is_new":           False,
#         "last_triaged_at":  last_triaged_at,
#         "last_severity":    last_severity,
#         "last_ai_severity": ai_severity,
#         "last_confidence":  last_confidence,
#         "root_cause":       root_cause,
#         "case_id":          last_triage.case_id,
#         "changes":          changes,
#         "needs_retriage":   True,
#     }


@router.get("/metrics")
async def get_metrics(user: User = Depends(get_current_user)):
    return await metrics_service.get_metrics()


# ── ORIGINAL FAT ROUTE (kept until confirmed working) ─────────────
# @router.get("/metrics")
# async def get_metrics(user: User = Depends(get_current_user)):
#     async with AsyncSessionLocal() as db:
#         summary = await get_metrics_summary(db)
#         recent  = await list_recent_pipeline_completions(
#             db, limit=10)
#         failed_result = await db.execute(
#             select(AuditLog.id).where(AuditLog.status == "failed")
#         )
#         failed_triages = len(failed_result.scalars().all())
#
#     all_connectors = await ConnectorRegistry.get_all_enabled()
#     bug_connectors = [
#         c for c in all_connectors
#         if c.system_type in _BUG_SOURCE_TYPES
#     ]
#
#     by_severity: dict[str, int] = {
#         "P0": 0, "P1": 0, "P2": 0, "P3": 0, "Unknown": 0}
#     source_counts: dict[str, int] = {}
#     total_confidence = 0.0
#     confidence_count = 0
#
#     for entry in recent:
#         s = (
#             (entry.summary or {}).get("unified_severity")
#             or (entry.summary or {}).get("severity", "Unknown")
#         )
#         if s not in by_severity:
#             s = "Unknown"
#         by_severity[s] += 1
#         src = entry.source_id or "unknown"
#         source_counts[src] = source_counts.get(src, 0) + 1
#         conf = (entry.summary or {}).get("confidence", 0)
#         if conf:
#             total_confidence += conf
#             confidence_count += 1
#
#     avg_confidence = (
#         round(total_confidence / confidence_count, 2)
#         if confidence_count else 0)
#
#     # Live P0/P1 counts from Redis-cached bug data
#     live_p0 = 0
#     live_p1 = 0
#     live_total = 0
#     try:
#         for connector in bug_connectors:
#             cached = await get_cached_buglist(
#                 connector.source_id, "open", "")
#             if cached:
#                 for bug in cached:
#                     live_total += 1
#                     sev = bug.get("severity", "Unknown")
#                     if sev == "P0":
#                         live_p0 += 1
#                     elif sev == "P1":
#                         live_p1 += 1
#     except Exception:
#         pass
#
#     today_start = datetime.now(timezone.utc).replace(
#         hour=0, minute=0, second=0, microsecond=0)
#     triaged_today = sum(
#         1 for e in recent
#         if e.created_at and e.created_at >= today_start
#     )
#
#     total_triages = summary.get("total_triaged", 0)
#     needs_triage  = max(0, live_total - total_triages)
#
#     return {
#         "total_triages":   total_triages,
#         "total_triaged":   total_triages,
#         "sources_online":  len(bug_connectors),
#         "sources_total":   len(bug_connectors),
#         "by_severity":     by_severity,
#         "by_source":       source_counts,
#         "avg_confidence":  avg_confidence,
#         "live_p0_count":   live_p0,
#         "live_p1_count":   live_p1,
#         "live_total_bugs": live_total,
#         "triaged_today":   triaged_today,
#         "needs_triage":    needs_triage,
#         "failed_triages":  failed_triages,
#         "recent_activity": [
#             {
#                 "case_id":    e.case_id or "",
#                 "bug_id":     e.bug_id,
#                 "source_id":  e.source_id or "",
#                 "severity":   (
#                     (e.summary or {}).get("unified_severity")
#                     or (e.summary or {}).get(
#                         "severity", "Unknown")),
#                 "confidence": (
#                     (e.summary or {}).get("confidence", 0)),
#                 "root_cause": (
#                     ((e.summary or {}).get(
#                         "root_cause") or "")[:100]),
#                 "duration_ms": e.duration_ms or 0,
#                 "engineer_id": e.engineer_id or "",
#                 "created_at":  (
#                     e.created_at.isoformat()
#                     if e.created_at else ""),
#             }
#             for e in recent
#         ],
#     }


@router.get("/history/triage")
async def get_triage_history(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        entries = await list_recent_pipeline_completions(
            db, limit=limit)

    results = []
    for e in entries:
        summary = e.summary or {}
        results.append({
            "id":              e.id,
            "case_id":         e.case_id or "",
            "bug_id":          e.bug_id,
            "source_id":       e.source_id or "",
            "engineer_id":     e.engineer_id or "",
            "severity":        (
                summary.get("severity")
                or summary.get(
                    "unified_severity", "Unknown")),
            "confidence":      summary.get("confidence", 0),
            "root_cause":      (
                summary.get("root_cause") or "")[:120],
            "duration_ms":     e.duration_ms or 0,
            "systems_queried": e.systems_queried or [],
            "triaged_at":      (
                e.created_at.isoformat()
                if e.created_at else None),
        })
    return results


@router.get("/cases/{case_id}")
async def get_case_result(
    case_id: str,
    user: User = Depends(get_current_user),
):
    return await case_service.get_case_result(case_id)


# ── ORIGINAL FAT ROUTE (kept until confirmed working) ─────────────
# @router.get("/cases/{case_id}")
# async def get_case_result(
#     case_id: str,
#     user: User = Depends(get_current_user),
# ):
#     from fastapi import HTTPException
#     from orchestrator.redis_client import (
#         get_cached_case_result,
#         get_redis,
#         get_stored_panels,
#     )
#     cached = await get_cached_case_result(case_id)
#     stored_panels = await get_stored_panels(case_id)
#     if not cached:
#         if not stored_panels:
#             raise HTTPException(
#                 status_code=404,
#                 detail=(
#                     "Case result not found. "
#                     "Results are cached for 1 hour after triage."),
#             )
#         return {
#             "case_id": case_id,
#             "status": "in_progress",
#             "from_cache": False,
#             "panels": stored_panels,
#             "context": _context_from_panels(stored_panels),
#         }
#
#     # BUG3: if Panel 2/3 are missing from cached context, recover from
#     # dedicated per-case keys (set by orchestrator after Phase 2)
#     ctx = cached.get("context", {})
#     try:
#         r = await get_redis()
#         if not ctx.get("related_tickets"):
#             val = await r.get(f"related:{case_id}")
#             if val:
#                 ctx["related_tickets"] = json.loads(val)
#         if not ctx.get("kb_articles"):
#             val = await r.get(f"kb:{case_id}")
#             if val:
#                 ctx["kb_articles"] = json.loads(val)
#         if not ctx.get("enrichment_sources"):
#             val = await r.get(f"enrichment:{case_id}")
#             if val:
#                 ctx["enrichment_sources"] = json.loads(val)
#         cached["context"] = ctx
#     except Exception:
#         pass
#
#     return cached


def _context_from_panels(panels: list[dict]) -> dict:
    ctx = {}
    for event in panels or []:
        panel = event.get("panel")
        data = event.get("data") or {}
        if panel == "bug_context":
            ctx.update({
                "bug_context": data.get("bug_context") or {},
                "primary_ticket": data.get("primary_ticket"),
                "components": data.get("components") or [],
                "customer_cases": data.get("customer_cases") or [],
                "customer_signals": data.get("customer_signals") or [],
                "source_references": data.get("source_references") or [],
            })
        elif panel == "related_issues":
            ctx["related_tickets"] = data.get("related_tickets") or []
            ctx["sources_queried"] = data.get("sources_queried") or []
        elif panel in {"linked_context", "knowledge_base"}:
            ctx["kb_articles"] = data.get("kb_articles") or []
            ctx["kb_reasoning"] = data.get("kb_reasoning") or ""
            if data.get("customer_cases"):
                ctx["customer_cases"] = data.get("customer_cases")
        elif panel == "ai_summary":
            ctx["synthesis"] = data.get("synthesis") or {}
            ctx["errors"] = data.get("errors") or {}
        elif event.get("type") == "pipeline_done":
            ctx["pipeline_done"] = event
    return ctx
