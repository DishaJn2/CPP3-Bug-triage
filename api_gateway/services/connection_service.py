import asyncio
import os
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from orchestrator.connectors.registry import ConnectorRegistry, SYSTEM_TYPE_TO_CLASS
from orchestrator.db.repositories.source_registry import (
    create_source,
    get_all_sources,
    get_source_by_id,
)
from orchestrator.db.session import AsyncSessionLocal


# ── Helpers (exact copies from settings_routes.py) ────────────────

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


# ── Public service function ───────────────────────────────────────

async def create_connection(
    display_name: str,
    system_type: str,
    base_url: str,
    port: Optional[int],
    auth_type: Optional[str],
    auth_token: Optional[str],
    project_key: Optional[str],
    ticket_prefix: Optional[str],
) -> dict:
    source_id = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    source_id = f"{source_id}-{system_type}"
    env_var_name = re.sub(r"[^A-Z0-9]+", "_", display_name.upper()).strip("_") + "_TOKEN"

    # SIDE EFFECT: env mutation happens before DB write — no rollback if DB write fails
    if auth_token:
        os.environ[env_var_name] = auth_token

    if system_type not in SYSTEM_TYPE_TO_CLASS:
        raise HTTPException(status_code=400, detail=f"Unknown system_type: {system_type}")

    cls = SYSTEM_TYPE_TO_CLASS[system_type]
    test_connector = cls(
        source_id=source_id,
        system_type=system_type,
        base_url=base_url,
        project_key=project_key or "",
        ticket_prefix=ticket_prefix or "",
        token=auth_token or "",
    )
    try:
        health = await asyncio.wait_for(
            test_connector.health_check(),
            timeout=10.0,
        )
        if not health.get("ok"):
            raise RuntimeError(health.get("error") or "health check failed")
        test_message = "Connection successful"
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Connection test failed: {str(e)[:200]}. Nothing was saved.",
        )

    async with AsyncSessionLocal() as db:
        existing = await get_source_by_id(db, source_id)
        if existing:
            raise HTTPException(status_code=409, detail=f"Connection '{source_id}' already exists")
        new_source = await create_source(db, {
            "source_id":       source_id,
            "display_name":    display_name,
            "system_type":     system_type,
            "base_url":        base_url,
            "port":            port,
            "auth_type":       auth_type or "bearer_token",
            "auth_secret_ref": env_var_name,
            "project_key":     project_key or "",
            "ticket_prefix":   ticket_prefix or "",
            "enabled":         True,
        })
        result = _format_source(new_source)

    ConnectorRegistry.invalidate_cache()
    return {"connection": result, "test_message": test_message, "status": "created"}


async def list_connections() -> dict:
    async with AsyncSessionLocal() as db:
        sources = await get_all_sources(db)
    health_by_source = {}
    try:
        health_results = await asyncio.wait_for(
            ConnectorRegistry.health_check_all(timeout=3.0),
            timeout=5.0,
        )
        health_by_source = {
            item.get("source_id"): item
            for item in health_results
            if item.get("source_id")
        }
    except Exception:
        health_by_source = {}

    connections = [
        _format_source(s, health_by_source.get(s.source_id))
        for s in sources
    ]
    return {
        "connections": connections,
        "total": len(connections),
        "by_type": {
            st: len([s for s in sources if s.system_type == st])
            for st in SYSTEM_TYPE_LABELS
        },
    }


async def test_connection(source_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        source = await get_source_by_id(db, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Connection not found")

    cls = SYSTEM_TYPE_TO_CLASS.get(source.system_type)
    if not cls:
        raise HTTPException(status_code=400, detail=f"No connector for type: {source.system_type}")

    token = os.environ.get(source.auth_secret_ref or "", "")
    connector = cls(
        source_id=source.source_id,
        system_type=source.system_type,
        base_url=source.base_url,
        project_key=source.project_key or "",
        ticket_prefix=source.ticket_prefix or "",
        token=token,
    )

    try:
        health = await asyncio.wait_for(connector.health_check(), timeout=10.0)
        if not health.get("ok"):
            raise RuntimeError(health.get("error") or "health check failed")
        return {
            "status": "ok",
            "source_id": source_id,
            "message": "Connected",
            "token_present": bool(token),
            "health_status": "Connected",
            "latency_ms": health.get("latency_ms", 0),
        }
    except Exception as e:
        message = str(e)[:300]
        health_status = "Timeout" if "timeout" in message.lower() else "Error"
        return {
            "status": "error",
            "source_id": source_id,
            "message": message,
            "token_present": bool(token),
            "health_status": health_status,
        }
