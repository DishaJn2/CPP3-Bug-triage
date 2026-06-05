from types import SimpleNamespace

import pytest

from api_gateway.routes.cases_routes import assemble_grouped_bug_list
from orchestrator.db.models import (
    AuditLog,
    BugGroupMapping,
    SystemGroupRegistry,
)
from orchestrator.db.repositories import group_registry


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeExecuteResult:
    def __init__(self, *, rows=None, scalars=None):
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self):
        return self._rows

    def scalars(self):
        return FakeScalarResult(self._scalars)


class SequencedDb:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("Unexpected DB execute")
        return self.results.pop(0)


class PersistDb:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None

    async def execute(self, _statement):
        return FakeExecuteResult()


@pytest.mark.asyncio
async def test_related_tickets_are_persisted_as_group_children(monkeypatch):
    db = PersistDb()

    async def no_existing_group(_db, _tickets):
        return None

    async def next_group_id(_db):
        return "BT-001"

    async def create_group(_db, group_id, title, priority, primary_source_id):
        return SystemGroupRegistry(
            group_id=group_id,
            title=title,
            priority=priority,
            primary_source_id=primary_source_id,
        )

    async def no_existing_ticket(_db, _ticket_id, _source_id):
        return None

    monkeypatch.setattr(
        group_registry, "get_group_for_any_ticket", no_existing_group)
    monkeypatch.setattr(group_registry, "get_next_group_id", next_group_id)
    monkeypatch.setattr(group_registry, "create_group", create_group)
    monkeypatch.setattr(group_registry, "get_group_for_ticket",
                        no_existing_ticket)

    group_id = await group_registry.persist_related_issue_group(
        db,
        {
            "ticket_id": "STO-1",
            "source_id": "jira-storage",
            "system_type": "jira",
            "title": "Primary storage bug",
            "severity": "P1",
            "status": "open",
            "url": "https://jira.example/STO-1",
        },
        [
            {
                "ticket_id": "GH-7",
                "source": "github",
                "system_type": "github",
                "title": "Related GitHub issue",
                "status": "open",
                "url": "https://github.example/issues/7",
                "similarity_score": 0.88,
                "similarity_label": "Good Match",
                "similarity_reason": "Same stack trace",
            }
        ],
    )

    assert group_id == "BT-001"
    assert len(db.added) == 2
    root, child = db.added
    assert root.role == "root"
    assert root.raw_ticket_id == "STO-1"
    assert child.role == "child"
    assert child.raw_ticket_id == "GH-7"
    assert child.similarity_score == 0.88
    assert child.similarity_reason == "Same stack trace"


@pytest.mark.asyncio
async def test_bugs_returns_expanded_group_with_root_and_children():
    live_bugs = [{
        "ticket_id": "STO-1",
        "source_id": "jira-storage",
        "system_type": "jira",
        "title": "Primary live title",
        "severity": "P1",
        "status": "open",
        "url": "https://jira.example/STO-1",
    }]
    mappings = [
        BugGroupMapping(
            group_id="BT-001",
            raw_ticket_id="STO-1",
            source_id="jira-storage",
            system_type="jira",
            role="root",
            title="Primary persisted title",
            severity="P1",
            status="open",
            url="https://jira.example/STO-1",
        ),
        BugGroupMapping(
            group_id="BT-001",
            raw_ticket_id="GH-7",
            source_id="github",
            system_type="github",
            role="child",
            title="Related GitHub issue",
            severity="P2",
            status="open",
            url="https://github.example/issues/7",
            similarity_score=0.88,
            similarity_label="Good Match",
            similarity_reason="Same stack trace",
        ),
    ]
    db = SequencedDb([
        FakeExecuteResult(rows=[
            SimpleNamespace(raw_ticket_id="STO-1", group_id="BT-001")
        ]),
        FakeExecuteResult(scalars=[
            SystemGroupRegistry(
                group_id="BT-001",
                title="Storage group",
                priority="P1",
                status="active",
            )
        ]),
        FakeExecuteResult(scalars=mappings),
        FakeExecuteResult(scalars=[
            AuditLog(
                bug_id="STO-1",
                step="pipeline_complete",
                summary={"severity": "P1", "confidence": 0.9},
            )
        ]),
    ])

    result = await assemble_grouped_bug_list(live_bugs, db)

    assert result["ungrouped"] == []
    group = result["groups"][0]
    assert group["root"]["ticket_id"] == "STO-1"
    assert group["root"]["title"] == "Primary live title"
    assert group["children"][0]["ticket_id"] == "GH-7"
    assert group["children"][0]["title"] == "Related GitHub issue"
    assert group["children"][0]["similarity_score"] == 0.88
    assert group["child_count"] == 1


@pytest.mark.asyncio
async def test_group_children_return_even_if_not_in_live_page():
    live_bugs = [{"ticket_id": "STO-1", "title": "Primary"}]
    db = SequencedDb([
        FakeExecuteResult(rows=[
            SimpleNamespace(raw_ticket_id="STO-1", group_id="BT-002")
        ]),
        FakeExecuteResult(scalars=[
            SystemGroupRegistry(group_id="BT-002", title="Group")
        ]),
        FakeExecuteResult(scalars=[
            BugGroupMapping(
                group_id="BT-002",
                raw_ticket_id="STO-1",
                source_id="jira-storage",
                system_type="jira",
                role="root",
            ),
            BugGroupMapping(
                group_id="BT-002",
                raw_ticket_id="BZ-99",
                source_id="bugzilla",
                system_type="bugzilla",
                role="child",
                title="Persisted child only",
            ),
        ]),
        FakeExecuteResult(scalars=[]),
    ])

    result = await assemble_grouped_bug_list(live_bugs, db)

    assert result["groups"][0]["root"]["ticket_id"] == "STO-1"
    assert result["groups"][0]["children"][0]["ticket_id"] == "BZ-99"
    assert result["groups"][0]["children"][0]["title"] == "Persisted child only"


@pytest.mark.asyncio
async def test_old_fallback_groups_without_root_still_render_shape():
    live_bugs = [{"ticket_id": "STO-1", "title": "Primary"}]
    db = SequencedDb([
        FakeExecuteResult(rows=[
            SimpleNamespace(raw_ticket_id="STO-1", group_id="BT-003")
        ]),
        FakeExecuteResult(scalars=[
            SystemGroupRegistry(group_id="BT-003", title="Old Group")
        ]),
        FakeExecuteResult(scalars=[
            BugGroupMapping(
                group_id="BT-003",
                raw_ticket_id="STO-1",
                source_id="jira-storage",
                system_type="jira",
                role="child",
            ),
            BugGroupMapping(
                group_id="BT-003",
                raw_ticket_id="GH-2",
                source_id="github",
                system_type="github",
                role="child",
                title="Old child",
            ),
        ]),
        FakeExecuteResult(scalars=[]),
    ])

    result = await assemble_grouped_bug_list(live_bugs, db)

    assert result["groups"][0]["root"]["ticket_id"] == "STO-1"
    assert result["groups"][0]["children"][0]["ticket_id"] == "GH-2"
