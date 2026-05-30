import asyncio
import json
import structlog
from fastapi import WebSocket
from orchestrator.redis_client import get_redis

log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, case_id: str, websocket: WebSocket) -> None:
        self.active_connections[case_id] = websocket
        log.info("WebSocket connected", case_id=case_id)

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
            await pubsub.subscribe(f"ws:{case_id}")
            log.info("Subscribed to Redis channel", case_id=case_id)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    raw = message.get("data", "")
                    try:
                        parsed = json.loads(raw)
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
