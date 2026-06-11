import asyncio
import dataclasses
import time
from collections import defaultdict
from datetime import datetime, timezone

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.connectors.registry import ConnectorRegistry
from orchestrator.db.models import AuditLog, BugGroupMapping, SystemGroupRegistry
from orchestrator.db.repositories.audit_log import get_last_triage_for_bug
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.redis_client import cache_buglist, get_cached_buglist
from orchestrator.utils.url_utils import sanitize_bug_url

_BUG_SOURCE_TYPES = {"github", "jira", "jira_apache", "bugzilla"}
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Unknown": 4}


# ── Helpers (exact copies from cases_routes.py) ───────────────────

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


async def _fetch_buglist_for_connector(
        connector,
        status: str,
        severity: str,
        max_results: int) -> dict:
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
            timeout=20.0,
        )
        bugs = [
            _normalize_list_bug(ticket, connector)
            for ticket in (tickets or [])
        ]
        await cache_buglist(
            connector.source_id, status, severity, bugs, ttl=120)
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


# ── Public service function ───────────────────────────────────────

async def get_bugs(
    page: int,
    page_size: int,
    search: str,
    severity: str,
    source: str,
    status: str,
    sort_field: str,
    sort_order: str,
) -> dict:
    all_connectors = await ConnectorRegistry.get_all_enabled()
    connectors = [
        c for c in all_connectors
        if c.system_type in _BUG_SOURCE_TYPES
    ]
    if source:
        connectors = [
            c for c in connectors
            if c.source_id == source or c.system_type == source
        ]

    if not connectors:
        return {
            "ungrouped": [], "groups": [],
            "total": 0, "page": page,
            "page_size": page_size, "sources_online": 0,
            "sources_total": 0, "partial": False,
            "bugs": [],
            "source_errors": [],
            "message": "No connectors configured",
        }

    fetch_status = status or "open"
    fetch_severity = severity or ""
    max_results = max(page * page_size, 100)
    fetch_results = await asyncio.gather(
        *[
            _fetch_buglist_for_connector(
                connector=c,
                status=fetch_status,
                severity=fetch_severity,
                max_results=max_results,
            )
            for c in connectors
        ],
        return_exceptions=True,
    )

    all_bugs = []
    source_errors = []
    cache_statuses = []
    for connector, result in zip(connectors, fetch_results):
        if isinstance(result, Exception):
            source_errors.append({
                "source_id": connector.source_id,
                "system_type": connector.system_type,
                "message": str(result)[:300],
            })
            continue

        all_bugs.extend(result.get("bugs") or [])
        cache_statuses.append(result.get("cache_status", "miss"))
        if result.get("error"):
            source_errors.append(result["error"])

    sources_online = len(connectors) - len(source_errors)

    # Filters
    if search:
        sl = search.strip().lower()

        def matches(b: dict) -> bool:
            if sl in (b.get("ticket_id") or "").lower():
                return True
            if sl in (b.get("title") or "").lower():
                return True
            if sl in (b.get("component") or "").lower():
                return True
            if sl in (b.get("source_id") or "").lower():
                return True
            if sl in (b.get("source_display_name") or "").lower():
                return True
            if sl in (b.get("system_type") or "").lower():
                return True
            if sl in (b.get("severity") or "").lower():
                return True
            if sl in (b.get("status") or "").lower():
                return True
            desc = (b.get("description") or "")[:200].lower()
            if sl in desc:
                return True
            for label in (b.get("labels") or []):
                if sl in str(label).lower():
                    return True
            return False

        all_bugs = [b for b in all_bugs if matches(b)]
    if severity:
        all_bugs = [
            b for b in all_bugs
            if b.get("severity", "") == severity
        ]
    if status:
        all_bugs = [
            b for b in all_bugs
            if b.get("status", "").lower() == status.lower()
        ]

    all_bugs.sort(
        key=lambda b: SEVERITY_ORDER.get(
            b.get("severity", "Unknown"), 4))
    total     = len(all_bugs)
    start_idx = (page - 1) * page_size
    page_bugs = all_bugs[start_idx: start_idx + page_size]

    # Assemble grouped tree (all DB lookups are IN-queries)
    assembled: dict = {"ungrouped": [], "groups": []}
    try:
        async with AsyncSessionLocal() as db:
            assembled = await assemble_grouped_bug_list(
                raw_bugs=page_bugs, db=db)
    except Exception as e:
        print(f"[BugList] assemble_grouped_bug_list failed: {e}",
              flush=True)
        for bug in page_bugs:
            bug["type"]       = "standalone"
            bug["is_triaged"] = False
            bug["triage_info"] = None
        assembled = {"ungrouped": page_bugs, "groups": []}

    # Build flat bugs list for frontend (ungrouped + group root/children)
    flat_bugs = assembled.get("ungrouped", []) + [
        item
        for group in assembled.get("groups", [])
        for item in ([group.get("root")] + group.get("children", []))
        if item
    ]

    if not cache_statuses:
        cache_status = "error"
    elif all(s == "hit" for s in cache_statuses):
        cache_status = "hit"
    elif any(s == "hit" for s in cache_statuses):
        cache_status = "partial"
    else:
        cache_status = "miss"

    response = {
        **assembled,
        "bugs":          flat_bugs,
        "total":         total,
        "page":          page,
        "page_size":     page_size,
        "sources_online": sources_online,
        "sources_total": len(connectors),
        "partial":       bool(source_errors),
        "source_errors": source_errors,
        "cache_status":  cache_status,
        "cached_at":     time.time(),
    }

    return response


async def get_bug_status(bug_id: str) -> dict:
    # Step 1: Fetch last audit record
    async with AsyncSessionLocal() as db:
        last_triage = await get_last_triage_for_bug(db, bug_id)

    if not last_triage:
        return {
            "is_new":           True,
            "needs_retriage":   True,
            "changes":          [],
            "last_triaged_at":  None,
            "last_severity":    None,
            "last_confidence":  None,
        }

    summary           = last_triage.summary or {}
    ticket_updated_at = summary.get("ticket_updated_at") or summary.get("updated_at", "")
    last_severity     = summary.get("ticket_severity") or summary.get("severity", "")
    last_status       = summary.get("ticket_status") or summary.get("status", "")
    ai_severity       = summary.get("ai_severity") or summary.get("severity", "")
    root_cause        = summary.get("root_cause", "")
    last_confidence   = summary.get("confidence", 0)
    last_triaged_at   = (
        last_triage.created_at.isoformat()
        if last_triage.created_at else None
    )

    # Step 1b: Resolve connector
    connector = None
    try:
        connector = await ConnectorRegistry.get_connector(
            last_triage.source_id or "")
    except Exception:
        pass

    if not connector:
        try:
            connectors  = await ConnectorRegistry.get_all_enabled()
            bug_upper   = bug_id.upper()
            sorted_c    = sorted(
                connectors,
                key=lambda c: len(c.ticket_prefix or ""),
                reverse=True)
            for c in sorted_c:
                prefix = (c.ticket_prefix or "").upper().strip()
                if prefix and bug_upper.startswith(prefix):
                    connector = c
                    break
        except Exception:
            pass

    if not connector:
        return {
            "is_new":           False,
            "last_triaged_at":  last_triaged_at,
            "last_severity":    last_severity,
            "last_ai_severity": ai_severity,
            "last_confidence":  last_confidence,
            "root_cause":       root_cause,
            "case_id":          last_triage.case_id,
            "changes":          [],
            "needs_retriage":   None,
        }

    # Step 2: Lightweight freshness check
    live = {}
    try:
        live = await asyncio.wait_for(
            connector.get_lightweight(bug_id),
            timeout=8.0)
    except Exception as e:
        structlog.get_logger().warning(
            "get_lightweight failed",
            bug_id=bug_id, error=str(e))

    if not live:
        return {
            "is_new":           False,
            "last_triaged_at":  last_triaged_at,
            "last_severity":    last_severity,
            "last_ai_severity": ai_severity,
            "last_confidence":  last_confidence,
            "root_cause":       root_cause,
            "case_id":          last_triage.case_id,
            "changes":          [],
            "needs_retriage":   False,
        }

    # Step 3: Decide path
    live_updated_at = live.get("updated_at", "")
    live_severity   = live.get("severity", "")
    live_status     = live.get("status", "")

    def to_datetime(val) -> datetime:
        if isinstance(val, datetime):
            return val
        if not val:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            s = str(val).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            if len(s) > 5 and s[-5] in ('+', '-'):
                s = s[:-2] + ":" + s[-2:]
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    last_triaged_dt = to_datetime(last_triage.created_at)
    live_updated_dt = to_datetime(live_updated_at)

    no_change = (
        live_updated_dt <= last_triaged_dt
        and live_severity == last_severity
        and live_status   == last_status
    )

    if no_change:
        return {
            "is_new":           False,
            "last_triaged_at":  last_triaged_at,
            "last_severity":    last_severity,
            "last_ai_severity": ai_severity,
            "last_confidence":  last_confidence,
            "root_cause":       root_cause,
            "case_id":          last_triage.case_id,
            "changes":          [],
            "needs_retriage":   False,
        }

    # Step 4: Change detected — fetch detailed changelog
    changelog = []
    try:
        changelog = await asyncio.wait_for(
            connector.get_changelog(
                bug_id, since=last_triaged_at),
            timeout=10.0)
    except Exception:
        pass

    # Step 5: Filter and build response
    relevant = {
        "priority", "status", "severity",
        "assignee", "resolution", "description"
    }
    changes = [
        {
            "field":      e.field,
            "from":       e.old_value,
            "to":         e.new_value,
            "changed_at": e.changed_at,
            "changed_by": e.changed_by,
        }
        for e in changelog
        if e.field.lower() in relevant
    ]

    if not changes:
        if live_severity and live_severity != last_severity:
            changes.append({
                "field":      "severity",
                "from":       last_severity,
                "to":         live_severity,
                "changed_at": live_updated_at,
                "changed_by": "",
            })
        if live_status and live_status != last_status:
            changes.append({
                "field":      "status",
                "from":       last_status,
                "to":         live_status,
                "changed_at": live_updated_at,
                "changed_by": "",
            })

    return {
        "is_new":           False,
        "last_triaged_at":  last_triaged_at,
        "last_severity":    last_severity,
        "last_ai_severity": ai_severity,
        "last_confidence":  last_confidence,
        "root_cause":       root_cause,
        "case_id":          last_triage.case_id,
        "changes":          changes,
        "needs_retriage":   True,
    }
