import asyncio
import json

import api_gateway.websocket_manager as ws_module
import orchestrator.redis_client as redis_module
from api_gateway.websocket_manager import ConnectionManager
from orchestrator.orchestrator import TaskOrchestrator


def run(coro):
    return asyncio.run(coro)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.calls = []

    async def setex(self, key, ttl, value):
        self.calls.append(("setex", key, value))
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def rpush(self, key, value):
        self.calls.append(("rpush", key, value))
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            return values[start:]
        return values[start:end + 1]

    async def expire(self, key, ttl):
        self.calls.append(("expire", key, ttl))

    async def publish(self, channel, message):
        self.calls.append(("publish", channel, message))

    def pubsub(self):
        return FakePubSub()


class FakePubSub:
    async def subscribe(self, channel):
        return None

    async def unsubscribe(self, channel):
        return None


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_panel_updates_are_cached_before_send(monkeypatch):
    fake = FakeRedis()

    async def get_fake_redis():
        return fake

    monkeypatch.setattr(redis_module, "get_redis", get_fake_redis)
    monkeypatch.setattr("orchestrator.orchestrator.get_redis", get_fake_redis)

    run(TaskOrchestrator()._publish_panel(
        "case-1",
        "bug_context",
        {"bug_context": {"ticket_id": "BUG-1"}},
        agent="ContextFetchAgent",
    ))

    call_names = [call[0] for call in fake.calls]
    assert call_names.index("setex") < call_names.index("publish")
    assert "panel:case-1:bug_context" in fake.values


def test_reconnect_replays_missed_panels_and_pipeline_done_last(monkeypatch):
    panels = [
        {"panel": "bug_context", "data": {"ok": 1}},
        {"panel": "related_issues", "data": {"ok": 2}},
        {
            "type": "pipeline_done",
            "case_id": "case-1",
            "status": "completed",
            "panels": [
                "bug_context",
                "related_issues",
                "knowledge_base",
                "ai_summary",
            ],
        },
    ]

    async def fake_get_stored_panels(case_id):
        return panels

    async def fake_get_redis():
        return FakeRedis()

    monkeypatch.setattr(ws_module, "get_stored_panels", fake_get_stored_panels)
    monkeypatch.setattr(ws_module, "get_redis", fake_get_redis)

    websocket = FakeWebSocket()
    run(ConnectionManager().subscribe_and_forward("case-1", websocket))

    assert websocket.sent == panels
    assert websocket.sent[-1]["type"] == "pipeline_done"


def test_websocket_disconnect_does_not_stop_panel_publish(monkeypatch):
    fake = FakeRedis()

    async def get_fake_redis():
        return fake

    monkeypatch.setattr(redis_module, "get_redis", get_fake_redis)
    monkeypatch.setattr("orchestrator.orchestrator.get_redis", get_fake_redis)

    manager = ConnectionManager()
    manager.disconnect("case-1")
    run(TaskOrchestrator()._publish_panel(
        "case-1",
        "related_issues",
        {"related_tickets": []},
        agent="CrossSystemFetchAgent",
    ))

    published = [call for call in fake.calls if call[0] == "publish"]
    stored = json.loads(fake.values["panel:case-1:related_issues"])
    assert published
    assert stored["panel"] == "related_issues"
