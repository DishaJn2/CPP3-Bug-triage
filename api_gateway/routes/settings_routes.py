from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
from urllib.parse import urlparse
from ..auth import get_current_user, User
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.repositories.source_registry import (
    get_all_sources, get_source_by_id, create_source,
    set_source_enabled, update_source
)
from orchestrator.connectors.registry import ConnectorRegistry, SYSTEM_TYPE_TO_CLASS
from ..services import connection_service

router = APIRouter(tags=["settings"])

SYSTEM_TYPE_LABELS = {
    "github":          {"label": "GitHub",           "icon": "GH",   "color": "purple"},
    "jira":            {"label": "JIRA",             "icon": "J",    "color": "blue"},
    "jira_apache":     {"label": "Apache JIRA",      "icon": "J",    "color": "blue"},
    "jira_cloud":      {"label": "JIRA Cloud",       "icon": "J",    "color": "blue"},
    "bugzilla":        {"label": "Bugzilla",         "icon": "BZ",   "color": "amber"},
    "confluence":      {"label": "Confluence",       "icon": "CF",   "color": "teal"},
    "customer_portal": {"label": "Customer Portal",  "icon": "CP",   "color": "green"},
    "support_kb":      {"label": "Support KB",       "icon": "KB",   "color": "teal"},
}


class ConnectionCreate(BaseModel):
    display_name: str
    system_type: str
    base_url: str
    port: Optional[int] = None
    auth_type: Optional[str] = "bearer_token"
    auth_token: Optional[str] = ""
    project_key: Optional[str] = ""
    ticket_prefix: Optional[str] = ""


class ConnectionUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    port: Optional[int] = None
    auth_type: Optional[str] = None
    auth_token: Optional[str] = None
    token: Optional[str] = None
    project_key: Optional[str] = None
    ticket_prefix: Optional[str] = None
    enabled: Optional[bool] = None


def _access_type_for_source(s, token_present: bool) -> str:
    auth_type = (s.auth_type or "none").strip().lower()
    if auth_type not in {"", "none", "public"}:
        return "Authenticated"
    if token_present:
        return "Authenticated"

    host = (urlparse(s.base_url or "").hostname or "").lower()
    private_markers = (
        "localhost",
        "127.",
        "10.",
        "192.168.",
        ".local",
        ".internal",
        ".corp",
        "intranet",
        "hpe",
        "cpp3",
    )
    if any(marker in host for marker in private_markers):
        return "Internal"
    return "Public"


def _health_status_from_result(result: dict | None, enabled: bool) -> str:
    if not enabled:
        return "Disconnected"
    if not result:
        return ""
    if result.get("connected") is True or result.get("is_connected") is True:
        return "Connected"
    if result.get("connected") is False or result.get("is_connected") is False:
        return "Disconnected"
    nested = result.get("test_result") if isinstance(result.get("test_result"), dict) else {}
    if nested:
        nested_status = _health_status_from_result(nested, enabled)
        if nested_status:
            return nested_status
    status = (result.get("status") or "").strip().lower()
    if result.get("ok") is True or status in {"ok", "connected", "success", "healthy"}:
        return "Connected"
    if status in {"disconnected", "disabled", "not_connected"}:
        return "Disconnected"
    if status == "timeout":
        return "Timeout"
    if status in {"error", "failed", "failure"}:
        return "Error"
    return ""


def _format_source(s, health: dict | None = None) -> dict:
    meta = SYSTEM_TYPE_LABELS.get(s.system_type, {"label": s.system_type, "icon": "?", "color": "gray"})
    token_env_var = s.auth_secret_ref or ""
    token_present = bool(os.environ.get(token_env_var, ""))
    access_type = _access_type_for_source(s, token_present)
    health_status = _health_status_from_result(health, s.enabled)
    return {
        "source_id":       s.source_id,
        "display_name":    s.display_name,
        "system_type":     s.system_type,
        "system_label":    meta["label"],
        "icon":            meta["icon"],
        "color":           meta["color"],
        "base_url":        s.base_url,
        "port":            s.port,
        "auth_type":       s.auth_type,
        "project_key":     s.project_key or "",
        "ticket_prefix":   s.ticket_prefix or "",
        "auth_secret_ref": token_env_var,
        "token_present":   token_present,
        "token_masked":    "••••••••" if token_present else "(not set — public API)",
        "access_type":     access_type,
        "health_status":   health_status,
        "health_error":    (health or {}).get("error", ""),
        "latency_ms":      (health or {}).get("latency_ms", 0),
        "enabled":         s.enabled,
        "created_at":      s.created_at.isoformat() if s.created_at else "",
    }


@router.get("/settings/connections")
async def list_connections(user: User = Depends(get_current_user)):
    return await connection_service.list_connections()


@router.post("/settings/connections")
async def add_connection(
    body: ConnectionCreate,
    user: User = Depends(get_current_user),
):
    return await connection_service.create_connection(
        display_name=body.display_name,
        system_type=body.system_type,
        base_url=body.base_url,
        port=body.port,
        auth_type=body.auth_type,
        auth_token=body.auth_token,
        project_key=body.project_key,
        ticket_prefix=body.ticket_prefix,
    )


@router.put("/settings/connections/{source_id}")
async def update_connection(
    source_id: str,
    body: ConnectionUpdate,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        source = await get_source_by_id(db, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Connection not found")

        updates = {}
        if body.display_name is not None:
            updates["display_name"] = body.display_name
        if body.base_url is not None:
            updates["base_url"] = body.base_url.rstrip("/")
        if body.port is not None:
            updates["port"] = body.port
        if body.auth_type is not None:
            updates["auth_type"] = body.auth_type
        if body.project_key is not None:
            updates["project_key"] = body.project_key
        if body.ticket_prefix is not None:
            updates["ticket_prefix"] = body.ticket_prefix
        if body.enabled is not None:
            updates["enabled"] = body.enabled

        new_token = body.auth_token or body.token
        if new_token:
            env_var = source.auth_secret_ref or ""
            if env_var:
                os.environ[env_var] = new_token

        if updates:
            await update_source(db, source_id, updates)
            source = await get_source_by_id(db, source_id)

    ConnectorRegistry.invalidate_cache()
    return {"connection": _format_source(source), "status": "updated"}


@router.delete("/settings/connections/{source_id}")
async def remove_connection(
    source_id: str,
    user: User = Depends(get_current_user),
):
    async with AsyncSessionLocal() as db:
        source = await get_source_by_id(db, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Connection not found")
        await set_source_enabled(db, source_id, False)

    ConnectorRegistry.invalidate_cache()
    return {"status": "disabled", "source_id": source_id}


@router.put("/connections/{source_id}")
async def update_connection_legacy(
    source_id: str,
    payload: dict,
    user: User = Depends(get_current_user),
):
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403,
                            detail="Not authorized")
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import update as sql_update
            from orchestrator.db.models import SourceRegistry

            update_data = {}
            if "display_name" in payload:
                update_data["display_name"] = payload["display_name"]
            if "base_url" in payload:
                update_data["base_url"] = payload["base_url"].rstrip("/")
            if "project_key" in payload:
                update_data["project_key"] = payload["project_key"]
            if "ticket_prefix" in payload:
                update_data["ticket_prefix"] = payload["ticket_prefix"]
            if "token" in payload and payload["token"]:
                # Store token reference
                secret_ref = f"{source_id}_token".upper()
                import os
                os.environ[secret_ref] = payload["token"]
                update_data["auth_secret_ref"] = secret_ref

            if not update_data:
                raise HTTPException(status_code=400,
                                    detail="No fields to update")

            await db.execute(
                sql_update(SourceRegistry)
                .where(SourceRegistry.source_id == source_id)
                .values(**update_data)
            )
            await db.commit()

        # Invalidate connector cache
        from orchestrator.connectors.registry import ConnectorRegistry
        ConnectorRegistry.invalidate_cache()

        return {"status": "updated", "source_id": source_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/connections/{source_id}/test")
async def test_connection(
    source_id: str,
    user: User = Depends(get_current_user),
):
    return await connection_service.test_connection(source_id)


