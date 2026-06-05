import asyncio
import json

from orchestrator.agents import context_fetch as context_fetch_module
from orchestrator.agents.context_fetch import ContextFetchAgent
from orchestrator.models.ticket import TicketData
from orchestrator.orchestrator import TaskOrchestrator


REQUIRED_PANEL_FIELDS = {
    "ticket_id",
    "source_name",
    "title",
    "severity",
    "status",
    "component",
    "assignee",
    "updated_at",
    "description",
    "steps_to_reproduce",
    "error_excerpt",
    "customer_impact",
    "recent_comments",
    "linked_items",
    "url",
}


def run(coro):
    return asyncio.run(coro)


def make_ticket(ticket_id: str = "STO-1089") -> TicketData:
    return TicketData(
        ticket_id=ticket_id,
        title="StorageController NPE during VM provisioning",
        description="Full bug description",
        severity="P1",
        status="Open",
        component="StorageController",
        assignee="dev1",
        reporter="qa1",
        created_at="2026-06-01T10:00:00Z",
        updated_at="2026-06-04T12:00:00Z",
        source_id="jira-storage",
        system_type="jira",
        url="https://jira.example.test/browse/STO-1089",
        error_excerpt="NullPointerException at StorageController.allocate",
        steps_to_reproduce="1. Create VM\n2. Attach volume\n3. Provision",
        customer_impact="Provisioning is blocked for production VMs.",
        comments=[
            {"author": "qa1", "body": "Initial report"},
            {"author": "dev1", "body": "Investigating"},
            {"author": "dev2", "body": "Reproduced locally"},
            {"author": "dev3", "body": "Patch in progress"},
        ],
        labels=["storage", "npe"],
    )


class FakeConnector:
    def __init__(self, ticket=None, fail=False):
        self.source_id = "jira-storage"
        self.system_type = "jira"
        self.ticket_prefix = "STO"
        self.display_name = "JIRA Storage Team"
        self.ticket = ticket or make_ticket()
        self.fail = fail
        self.requested_ticket_id = None

    async def get_ticket(self, ticket_id: str):
        self.requested_ticket_id = ticket_id
        if self.fail:
            raise RuntimeError("source unavailable")
        return self.ticket

    async def get_linked_items(self, ticket_id: str):
        return [
            {
                "raw_id": "BUG-49201",
                "source": "bugzilla",
                "type": "relates",
                "title": "Related Bugzilla issue",
                "url": "https://bugzilla.example.test/show_bug.cgi?id=49201",
            }
        ]


class FakePortal:
    async def search(self, query: str, max_results: int = 3, **kwargs):
        return [
            TicketData(
                ticket_id="CASE-100",
                title="Customer case for provisioning failure",
                description="Customer production impact",
                severity="P1",
                status="Open",
                component="StorageController",
                assignee="",
                reporter="Acme Corp",
                created_at="",
                updated_at="",
                source_id="customer-portal",
                system_type="customer_portal",
            )
        ]


class FakeRegistry:
    connector = FakeConnector()
    portals = []

    @classmethod
    async def get(cls, source_id: str):
        return cls.connector if source_id == cls.connector.source_id else None

    @classmethod
    async def get_by_ticket_id(cls, ticket_id: str):
        if ticket_id.startswith(cls.connector.ticket_prefix):
            return cls.connector
        return None

    @classmethod
    async def get_all_by_type(cls, system_type: str):
        return cls.portals if system_type == "customer_portal" else []


class FakeRedis:
    def __init__(self):
        self.messages = []
        self.lists = {}

    async def setex(self, key, ttl, value):
        self.messages.append(("setex", key, value))

    async def rpush(self, key, value):
        self.messages.append(("rpush", key, value))
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            return values[start:]
        return values[start:end + 1]

    async def expire(self, key, ttl):
        self.messages.append(("expire", key, ttl))

    async def publish(self, channel, message):
        self.messages.append(("publish", channel, message))


def test_full_primary_ticket_is_fetched_and_normalized(monkeypatch):
    connector = FakeConnector()
    FakeRegistry.connector = connector
    FakeRegistry.portals = [FakePortal()]
    monkeypatch.setattr(context_fetch_module, "ConnectorRegistry", FakeRegistry)

    context = run(ContextFetchAgent().run({
        "bug_id": "STO-1089",
        "source_id": "jira-storage",
        "errors": {},
    }))

    primary = context["primary_ticket"]
    bug_context = context["bug_context"]

    assert primary["ticket_id"] == "STO-1089"
    assert primary["source_name"] == "JIRA Storage Team"
    assert primary["steps_to_reproduce"].startswith("1. Create VM")
    assert primary["customer_impact"] == "Provisioning is blocked for production VMs."
    assert bug_context["ticket_id"] == "STO-1089"
    assert bug_context["linked_items"][0]["raw_id"] == "BUG-49201"
    assert bug_context["customer_cases"][0]["case_id"] == "CASE-100"
    assert bug_context["customer_signals"][0]["case_id"] == "CASE-100"


def test_missing_source_id_resolves_using_ticket_prefix(monkeypatch):
    connector = FakeConnector()
    FakeRegistry.connector = connector
    FakeRegistry.portals = []
    monkeypatch.setattr(context_fetch_module, "ConnectorRegistry", FakeRegistry)

    context = run(ContextFetchAgent().run({
        "bug_id": "STO-1089",
        "source_id": "",
        "errors": {},
    }))

    assert connector.requested_ticket_id == "STO-1089"
    assert context["source_id"] == "jira-storage"
    assert context["primary_ticket"]["ticket_id"] == "STO-1089"


def test_panel_1_payload_contains_required_fields(monkeypatch):
    connector = FakeConnector()
    FakeRegistry.connector = connector
    FakeRegistry.portals = []
    monkeypatch.setattr(context_fetch_module, "ConnectorRegistry", FakeRegistry)
    fake_redis = FakeRedis()

    async def get_fake_redis():
        return fake_redis

    import orchestrator.redis_client as redis_client

    monkeypatch.setattr(redis_client, "get_redis", get_fake_redis)

    context = run(ContextFetchAgent().run({
        "bug_id": "STO-1089",
        "source_id": "jira-storage",
        "errors": {},
    }))
    payload = {
        "primary_ticket": context.get("primary_ticket"),
        "bug_context": context.get("bug_context"),
        "components": context.get("components") or [],
        "customer_cases": context.get("customer_cases") or [],
        "source_references": context.get("source_references") or [],
        "errors": context.get("errors") or {},
    }

    run(TaskOrchestrator()._publish_panel(
        "case-1",
        "bug_context",
        payload,
        agent="ContextFetchAgent",
        status="completed",
    ))

    published = [
        json.loads(message)
        for action, _channel, message in fake_redis.messages
        if action == "publish"
    ][0]

    assert published["panel"] == "bug_context"
    assert published["agent"] == "ContextFetchAgent"
    assert published["status"] == "completed"
    assert REQUIRED_PANEL_FIELDS <= set(published["data"]["bug_context"])


def test_fetch_failure_returns_structured_error_without_crashing(monkeypatch):
    connector = FakeConnector(fail=True)
    FakeRegistry.connector = connector
    FakeRegistry.portals = []
    monkeypatch.setattr(context_fetch_module, "ConnectorRegistry", FakeRegistry)

    context = run(ContextFetchAgent().run({
        "bug_id": "STO-1089",
        "source_id": "jira-storage",
        "errors": {},
    }))

    assert context["primary_ticket"] is None
    assert context["bug_context"]["ticket_id"] == "STO-1089"
    assert context["bug_context"]["source_id"] == "jira-storage"
    assert "source unavailable" in context["errors"]["context_fetch"]
    assert "source unavailable" in context["bug_context"]["errors"]["context_fetch"]


def test_context_fetch_attaches_customer_signals(monkeypatch):
    class SignalPortal:
        last_error = {}

        async def search(self, query: str, max_results: int = 3, **kwargs):
            ticket = TicketData(
                ticket_id="SO-123",
                title="Stack question about StorageController NPE",
                description="Question has 1200 views and score 12.",
                severity="P1",
                status="answered",
                component="",
                assignee="",
                reporter="dev-user",
                created_at="",
                updated_at="",
                source_id="customer-portal",
                system_type="customer_portal",
                url="https://stackoverflow.com/questions/123",
            )
            ticket.signal_metadata = {
                "case_id": "SO-123",
                "source": "Stack Overflow",
                "customer_name": "dev-user",
                "severity": "P1",
                "status": "answered",
                "summary": "Stack question about StorageController NPE",
                "impact": "Question has 1200 views and score 12.",
                "url": "https://stackoverflow.com/questions/123",
                "linked_ticket_id": "123",
                "signal_score": 0.92,
            }
            return [ticket]

    connector = FakeConnector()
    FakeRegistry.connector = connector
    FakeRegistry.portals = [SignalPortal()]
    monkeypatch.setattr(context_fetch_module, "ConnectorRegistry", FakeRegistry)

    context = run(ContextFetchAgent().run({
        "bug_id": "STO-1089",
        "source_id": "jira-storage",
        "errors": {},
    }))

    signal = context["bug_context"]["customer_signals"][0]
    assert signal == context["customer_signals"][0]
    assert signal["case_id"] == "SO-123"
    assert signal["source"] == "Stack Overflow"
    assert signal["customer_name"] == "dev-user"
    assert signal["signal_score"] == 0.92


def test_linked_items_without_urls_are_made_clickable():
    class JiraConnectorRef:
        system_type = "jira"
        base_url = "https://jira.example.test"
        project_key = ""

    linked = ContextFetchAgent()._normalize_linked_items(
        JiraConnectorRef(),
        [{"id": "STO-999", "type": "relates", "title": "Linked issue"}],
    )

    assert linked[0]["url"] == "https://jira.example.test/browse/STO-999"
