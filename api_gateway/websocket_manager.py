import asyncio
import json
import structlog
from fastapi import WebSocket
from orchestrator.redis_client import get_redis, get_stored_panels, get_cached_case_result

log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, case_id: str, websocket: WebSocket) -> None:
        # Do NOT call websocket.accept() here — caller already accepted
        self.active_connections[case_id] = websocket
        log.info("WebSocket registered", case_id=case_id)

    def disconnect(self, case_id: str) -> None:
        self.active_connections.pop(case_id, None)
        log.info("WebSocket disconnected", case_id=case_id)

    async def send_panel_update(self, case_id: str, panel_name: str, data: dict) -> None:
        ws = self.active_connections.get(case_id)
        if ws:
            try:
                await ws.send_json({"panel": panel_name, "data": data})
            except Exception as e:
                log.warning("Failed to send panel update", case_id=case_id, error=str(e))

    async def subscribe_and_forward(self, case_id: str, websocket: WebSocket) -> None:
        try:
            r = await get_redis()
            pubsub = r.pubsub()

            # Subscribe FIRST before replaying stored panels.
            # This prevents missing panels published between replay and listen start.
            await pubsub.subscribe(f"ws:{case_id}")
            log.info("Subscribed to Redis channel", case_id=case_id)

            # Replay any panels already published (race condition fix)
            stored = await get_stored_panels(case_id)
            panels_seen = set()
            for panel_msg in stored:
                panel_name = panel_msg.get("panel", "")
                panels_seen.add(panel_name)
                try:
                    await websocket.send_json(panel_msg)
                    log.info("Replayed stored panel", case_id=case_id, panel=panel_name)
                except Exception:
                    pass

            # If pipeline already complete and all panels replayed, send complete and return
            if len(stored) >= 4:
                cached = await get_cached_case_result(case_id)
                if cached:
                    ctx = cached.get("context", {})
                    synthesis = ctx.get("synthesis") or {}
                    try:
                        await websocket.send_json({
                            "type": "pipeline_complete",
                            "case_id": case_id,
                            "severity": synthesis.get("unified_severity"),
                            "confidence": synthesis.get("confidence"),
                        })
                    except Exception:
                        pass
                    await pubsub.unsubscribe(f"ws:{case_id}")
                    return

            # Listen for new panels via pub/sub (handles live pipeline and remaining panels)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    raw = message.get("data", "")
                    try:
                        parsed = json.loads(raw)
                        panel_name = parsed.get("panel", "")

                        # Skip panels we already replayed (dedup)
                        if panel_name and panel_name in panels_seen:
                            panels_seen.discard(panel_name)
                            continue

                        await websocket.send_json(parsed)
                        if parsed.get("type") == "pipeline_complete":
                            break
                    except Exception as e:
                        log.warning("Failed to forward ws message", error=str(e))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("subscribe_and_forward error", case_id=case_id, error=str(e))
        finally:
            try:
                await pubsub.unsubscribe(f"ws:{case_id}")
            except Exception:
                pass


manager = ConnectionManager()
