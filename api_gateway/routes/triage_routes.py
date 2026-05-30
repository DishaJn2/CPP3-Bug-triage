import asyncio
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from ..auth import get_current_user, User
from ..config import JWT_SECRET, JWT_ALGORITHM, ENABLE_LOCAL_PIPELINE_FALLBACK
from ..kafka_client import publish_triage_request
from ..websocket_manager import manager
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.repositories.source_registry import get_enabled_sources
from orchestrator.redis_client import get_cached_case_result

router = APIRouter(tags=["triage"])


class TriageRequest(BaseModel):
    bug_id: str


@router.post("/triage")
async def start_triage(
    body: TriageRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    bug_id = body.bug_id.strip()
    if not bug_id:
        raise HTTPException(status_code=400, detail="bug_id is required")

    source_id = None
    async with AsyncSessionLocal() as db:
        sources = await get_enabled_sources(db)
        for src in sources:
            prefix = (src.ticket_prefix or "").upper()
            if prefix and bug_id.upper().startswith(prefix):
                source_id = src.source_id
                break
        if not source_id and sources:
            for src in sources:
                if src.system_type == "github" and bug_id.isdigit():
                    source_id = src.source_id
                    break
        if not source_id and sources:
            source_id = sources[0].source_id

    if not source_id:
        raise HTTPException(status_code=400, detail="Could not determine source for bug_id")

    case_id = str(uuid4())
    producer = getattr(request.app.state, "kafka_producer", None)
    published = False

    if producer:
        published = await publish_triage_request(producer, case_id, bug_id, source_id, user.user_id)

    if not published and ENABLE_LOCAL_PIPELINE_FALLBACK:
        from orchestrator.orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        asyncio.create_task(orch.run(case_id, bug_id, source_id, user.user_id))

    return {"case_id": case_id, "bug_id": bug_id, "source_id": source_id, "status": "accepted"}


@router.get("/triage/{case_id}/result")
async def get_triage_result(case_id: str, user: User = Depends(get_current_user)):
    cached = await get_cached_case_result(case_id)
    if not cached:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return cached


@router.websocket("/triage/{case_id}/stream")
async def triage_stream(case_id: str, websocket: WebSocket, token: str = Query("")):
    # MUST accept first before any close calls
    await websocket.accept()

    if not token:
        await websocket.send_json({"type": "error", "message": "No token"})
        await websocket.close(code=4001)
        return

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not payload.get("sub"):
            await websocket.send_json({"type": "error", "message": "Unauthorized"})
            await websocket.close(code=4001)
            return
    except JWTError:
        await websocket.send_json({"type": "error", "message": "Invalid token"})
        await websocket.close(code=4001)
        return

    # Check if already completed (cached result)
    cached = await get_cached_case_result(case_id)
    if cached:
        ctx = cached.get("context", {})
        await websocket.send_json({"panel": "bug_context", "data": {
            "ticket": ctx.get("primary_ticket"),
            "keywords": ctx.get("keywords"),
            "components": ctx.get("components"),
        }})
        await websocket.send_json({"panel": "related_issues", "data": {
            "related_tickets": ctx.get("related_tickets", []),
            "sources_queried": ctx.get("sources_queried", []),
        }})
        await websocket.send_json({"panel": "linked_context", "data": {
            "kb_articles": ctx.get("kb_articles", []),
            "customer_cases": ctx.get("customer_cases", []),
        }})
        await websocket.send_json({"panel": "ai_summary", "data": {
            "synthesis": ctx.get("synthesis"),
        }})
        synthesis = ctx.get("synthesis") or {}
        await websocket.send_json({
            "type": "pipeline_complete",
            "case_id": case_id,
            "severity": synthesis.get("unified_severity"),
            "confidence": synthesis.get("confidence"),
        })
        await websocket.close()
        return

    # Live pipeline — subscribe to Redis and forward
    manager.active_connections[case_id] = websocket
    try:
        await manager.subscribe_and_forward(case_id, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(case_id)