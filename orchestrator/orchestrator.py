import asyncio
import json
import time
import structlog
from .agents import ContextFetchAgent, CrossSystemFetchAgent, EnrichmentAgent, AISynthesisAgent
from .db.session import AsyncSessionLocal
from .db.repositories.pipeline_context import (
    create_pipeline_context, get_pipeline_context,
    update_pipeline_step, delete_pipeline_context, get_steps_to_run,
)
from .db.repositories.audit_log import insert_audit_entry
from .redis_client import get_redis, publish_panel_update, cache_case_result

log = structlog.get_logger()


class TaskOrchestrator:
    async def run(self, case_id: str, bug_id: str, source_id: str, engineer_id: str) -> None:
        # Give the frontend 1.5 s to open WebSocket and subscribe before we start
        # publishing panels. This prevents the race condition where Panel 1 is
        # published before anyone is listening.
        await asyncio.sleep(1.5)

        start_time = time.monotonic()
        context = {
            "case_id": case_id,
            "bug_id": bug_id,
            "source_id": source_id,
            "engineer_id": engineer_id,
            "errors": {},
        }

        async with AsyncSessionLocal() as db:
            existing = await get_pipeline_context(db, case_id)
            if existing:
                resume_step = existing.current_step
                if existing.context_json:
                    context.update(existing.context_json)
                log.info("Resuming pipeline", case_id=case_id, from_step=resume_step)
            else:
                await create_pipeline_context(db, case_id, {})
                resume_step = "start"

        steps_to_run = get_steps_to_run(resume_step)

        if "context_fetch" in steps_to_run:
            context, _ = await ContextFetchAgent().safe_run(context)
            await self._checkpoint(case_id, "context_fetch", context)
            await self._publish_panel(case_id, "bug_context", {
                "primary_ticket": context.get("primary_ticket"),
                "keywords": context.get("keywords") or [],
                "components": context.get("components") or [],
                "customer_cases": context.get("customer_cases") or [],
                "errors": context.get("errors") or {},
            })

        if "cross_system_fetch" in steps_to_run or "enrichment" in steps_to_run:
            run_cross = "cross_system_fetch" in steps_to_run
            run_enrich = "enrichment" in steps_to_run

            if run_cross and run_enrich:
                results = await asyncio.gather(
                    CrossSystemFetchAgent().safe_run(context),
                    EnrichmentAgent().safe_run(context),
                    return_exceptions=True,
                )
                for res in results:
                    if isinstance(res, Exception):
                        log.warning("Phase 2 agent raised exception", error=str(res))
                    else:
                        ctx_result, _ = res
                        context.update(ctx_result)
            elif run_cross:
                context, _ = await CrossSystemFetchAgent().safe_run(context)
            elif run_enrich:
                context, _ = await EnrichmentAgent().safe_run(context)

            await self._checkpoint(case_id, "enrichment", context)
            await self._publish_panel(case_id, "related_issues", {
                "related_tickets": context.get("related_tickets") or [],
                "sources_queried": context.get("sources_queried") or [],
            })
            await self._publish_panel(case_id, "linked_context", {
                "kb_articles": context.get("kb_articles") or [],
                "kb_reasoning": context.get("kb_reasoning") or "",
                "customer_cases": context.get("customer_cases") or [],
            })

        if "ai_synthesis" in steps_to_run:
            context, _ = await AISynthesisAgent().safe_run(context)
            await self._checkpoint(case_id, "ai_synthesis", context)
            await self._publish_panel(case_id, "ai_summary", {
                "synthesis": context.get("synthesis") or {},
                "errors": context.get("errors") or {},
            })

        total_ms = int((time.monotonic() - start_time) * 1000)
        synthesis = context.get("synthesis") or {}

        await cache_case_result(case_id, {
            "case_id": case_id,
            "bug_id": bug_id,
            "source_id": source_id,
            "context": context,
        })

        async with AsyncSessionLocal() as db:
            await insert_audit_entry(db, {
                "case_id": case_id,
                "bug_id": bug_id,
                "source_id": source_id,
                "engineer_id": engineer_id,
                "step": "pipeline_complete",
                "status": "done",
                "summary": {
                    "severity": synthesis.get("unified_severity"),
                    "confidence": synthesis.get("confidence"),
                    "root_cause": synthesis.get("root_cause", "")[:200],
                    "updated_at": (context.get("primary_ticket") or {}).get("updated_at", ""),
                    "status": (context.get("primary_ticket") or {}).get("status", ""),
                },
                "systems_queried": context.get("sources_queried") or [],
                "duration_ms": total_ms,
            })
            await delete_pipeline_context(db, case_id)

        await self._publish_complete(case_id, synthesis, total_ms)
        log.info("Pipeline complete", case_id=case_id, duration_ms=total_ms)

    async def _checkpoint(self, case_id: str, step: str, context: dict) -> None:
        try:
            async with AsyncSessionLocal() as db:
                safe_ctx = {k: v for k, v in context.items() if k != "errors"}
                await update_pipeline_step(db, case_id, step, safe_ctx)
        except Exception as e:
            log.warning("Checkpoint failed", step=step, error=str(e))

    async def _publish_panel(self, case_id: str, panel_name: str, data: dict) -> None:
        await publish_panel_update(case_id, panel_name, data)

    async def _publish_complete(self, case_id: str, synthesis: dict, duration_ms: int) -> None:
        try:
            r = await get_redis()
            message = json.dumps({
                "type": "pipeline_complete",
                "case_id": case_id,
                "severity": synthesis.get("unified_severity"),
                "confidence": synthesis.get("confidence"),
                "duration_ms": duration_ms,
            })
            await r.publish(f"ws:{case_id}", message)
        except Exception as e:
            log.warning("publish_complete failed", error=str(e))
