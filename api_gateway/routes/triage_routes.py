import asyncio
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from ..auth import get_current_user, User
from ..config import JWT_SECRET, JWT_ALGORITHM, ENABLE_LOCAL_PIPELINE_FALLBACK
from ..kafka_client import publish_triage_request
from ..websocket_manager import manager
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.repositories.source_registry import get_enabled_sources
from orchestrator.redis_client import get_cached_case_result
import structlog

log = structlog.get_logger()

router = APIRouter(tags=["triage"])


class TriageRequest(BaseModel):
    bug_id: str
    source_id: str = ""  # Optional — if provided, skips server-side detection


@router.post("/triage")
async def start_triage(
    body: TriageRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    bug_id = body.bug_id.strip()
    if not bug_id:
        raise HTTPException(status_code=400, detail="bug_id is required")

    source_id = body.source_id.strip() if body.source_id else ""

    async with AsyncSessionLocal() as db:
        sources = await get_enabled_sources(db)

    if source_id:
        # Validate that provided source_id exists
        valid_ids = {s.source_id for s in sources}
        if source_id not in valid_ids:
            source_id = ""  # fall through to detection

    if not source_id:
        # Server-side source detection: prefix match first
        for src in sources:
            prefix = (src.ticket_prefix or "").upper()
            if prefix and bug_id.upper().startswith(prefix + "-"):
                source_id = src.source_id
                break
        # For numeric IDs without prefix, use first GitHub connector
        if not source_id:
            for src in sources:
                if src.system_type == "github" and bug_id.isdigit():
                    source_id = src.source_id
                    break
        # Last resort: first enabled source
        if not source_id and sources:
            source_id = sources[0].source_id

    if not source_id:
        raise HTTPException(status_code=400, detail="No source system configured")

    log.info("Starting triage", bug_id=bug_id, source_id=source_id, user=user.user_id)

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
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return cached


@router.websocket("/triage/{case_id}/stream")
async def triage_stream(
    case_id: str, websocket: WebSocket, token: str = Query("")
):
    # MUST accept first — cannot close without accepting
    await websocket.accept()

    if not token:
        await websocket.send_json({"type": "error", "message": "No token provided"})
        await websocket.close(code=4001)
        return

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_email = payload.get("sub", "")
        if not user_email:
            await websocket.send_json({"type": "error", "message": "Invalid token"})
            await websocket.close(code=4001)
            return
    except JWTError:
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4001)
        return

    # Register connection (accept already called above)
    manager.active_connections[case_id] = websocket

    try:
        # subscribe_and_forward handles both live pipelines and completed ones
        # (replays stored panels for race-condition fix, sends pipeline_complete if done)
        await manager.subscribe_and_forward(case_id, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("WebSocket error", case_id=case_id, error=str(e))
    finally:
        manager.disconnect(case_id)
