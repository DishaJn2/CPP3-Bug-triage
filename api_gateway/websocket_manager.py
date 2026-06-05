import json
import time
import structlog
from fastapi import WebSocket
from orchestrator.redis_client import get_redis, get_stored_panels

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

    async def subscribe_and_forward(self, case_id: str,
                                     websocket: WebSocket) -> None:
        pubsub = None
        try:
            r = await get_redis()
            pubsub = r.pubsub()

            # Subscribe FIRST before replaying
            await pubsub.subscribe(f"ws:{case_id}")

            sent = set()
            try:
                for parsed in await get_stored_panels(case_id):
                    name = parsed.get(
                        "panel", parsed.get("type", ""))
                    await websocket.send_json(parsed)
                    sent.add(name)
                    log.info("Replayed panel",
                             case_id=case_id, panel=name)
                    if parsed.get("type") == "pipeline_done":
                        return
            except Exception as e:
                log.warning("Replay error",
                            case_id=case_id, error=str(e))

            # Listen for new messages
            last_ping = time.monotonic()
            while True:
                if time.monotonic() - last_ping >= 15:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "case_id": case_id,
                    })
                    last_ping = time.monotonic()

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message:
                    continue
                if message["type"] != "message":
                    continue
                raw = message.get("data", "")
                try:
                    parsed = json.loads(raw)
                    panel = parsed.get(
                        "panel", parsed.get("type", ""))
                    if panel in sent:
                        continue
                    await websocket.send_json(parsed)
                    sent.add(panel)
                    if parsed.get("type") == "pipeline_done":
                        break
                except Exception as e:
                    log.warning("Forward error", error=str(e))

        except Exception as e:
            log.warning("WS error", case_id=case_id, error=str(e))
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe(f"ws:{case_id}")
            except Exception:
                pass


manager = ConnectionManager()
