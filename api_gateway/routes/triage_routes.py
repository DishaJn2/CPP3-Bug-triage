import asyncio
import os
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
from ..services import triage_service
import structlog

log = structlog.get_logger()

router = APIRouter(tags=["triage"])


class TriageRequest(BaseModel):
    bug_id: str
    source_id: str = ""        # Optional — if provided, skips server-side detection
    force_refresh: bool = False  # If True, bypass LLM result cache


@router.post("/triage")
async def start_triage(
    body: TriageRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    bug_id = body.bug_id.strip()
    if not bug_id:
        raise HTTPException(status_code=400, detail="bug_id is required")

    kafka_producer = getattr(request.app.state, "kafka_producer", None)
    return await triage_service.start_triage(
        bug_id=bug_id,
        source_id=body.source_id.strip() if body.source_id else "",
        user_id=user.user_id,
        force_refresh=body.force_refresh,
        kafka_producer=kafka_producer,
    )


@router.get("/triage/{case_id}/result")
async def get_triage_result(case_id: str, user: User = Depends(get_current_user)):
    return await triage_service.get_triage_result(case_id)


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
