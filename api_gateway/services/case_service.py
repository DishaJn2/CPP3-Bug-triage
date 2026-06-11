import json

from fastapi import HTTPException

from orchestrator.redis_client import (
    get_cached_case_result,
    get_redis,
    get_stored_panels,
)


# ── Helper (exact copy from cases_routes.py) ──────────────────────

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


# ── Public service function ───────────────────────────────────────

async def get_case_result(case_id: str) -> dict:
    cached = await get_cached_case_result(case_id)
    stored_panels = await get_stored_panels(case_id)
    if not cached:
        if not stored_panels:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Case result not found. "
                    "Results are cached for 1 hour after triage."),
            )
        return {
            "case_id": case_id,
            "status": "in_progress",
            "from_cache": False,
            "panels": stored_panels,
            "context": _context_from_panels(stored_panels),
        }

    # BUG3: if Panel 2/3 are missing from cached context, recover from
    # dedicated per-case keys (set by orchestrator after Phase 2)
    ctx = cached.get("context", {})
    try:
        r = await get_redis()
        if not ctx.get("related_tickets"):
            val = await r.get(f"related:{case_id}")
            if val:
                ctx["related_tickets"] = json.loads(val)
        if not ctx.get("kb_articles"):
            val = await r.get(f"kb:{case_id}")
            if val:
                ctx["kb_articles"] = json.loads(val)
        if not ctx.get("enrichment_sources"):
            val = await r.get(f"enrichment:{case_id}")
            if val:
                ctx["enrichment_sources"] = json.loads(val)
        cached["context"] = ctx
    except Exception:
        pass

    return cached
