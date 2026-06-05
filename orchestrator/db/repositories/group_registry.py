from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SystemGroupRegistry, BugGroupMapping


async def get_next_group_id(db: AsyncSession) -> str:
    result = await db.execute(
        select(func.count(SystemGroupRegistry.group_id))
    )
    count = result.scalar() or 0
    return f"BT-{(count + 1):03d}"


async def create_group(db: AsyncSession, group_id: str, title: str,
                        priority: str, primary_source_id: str) -> SystemGroupRegistry:
    group = SystemGroupRegistry(
        group_id=group_id,
        title=title,
        priority=priority,
        primary_source_id=primary_source_id,
        status="active",
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def get_group_for_ticket(db: AsyncSession, raw_ticket_id: str,
                                source_id: str) -> str | None:
    result = await db.execute(
        select(BugGroupMapping.group_id)
        .where(
            BugGroupMapping.raw_ticket_id == raw_ticket_id,
            BugGroupMapping.source_id == source_id,
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


async def get_group_for_any_ticket(db: AsyncSession,
                                    tickets: list[dict]) -> str | None:
    for t in tickets:
        gid = await get_group_for_ticket(
            db,
            t.get("ticket_id", ""),
            t.get("source_id", "")
        )
        if gid:
            return gid
    return None


async def add_tickets_to_group(db: AsyncSession, group_id: str,
                                tickets: list[dict]) -> None:
    for t in tickets:
        existing = await get_group_for_ticket(
            db,
            t.get("ticket_id", ""),
            t.get("source_id", "")
        )
        if not existing:
            mapping = BugGroupMapping(
                group_id=group_id,
                raw_ticket_id=t.get("ticket_id", ""),
                source_id=t.get("source_id", ""),
                system_type=t.get("system_type", ""),
                role=t.get("role", "child"),
                title=t.get("title", ""),
                url=t.get("url", ""),
                status=t.get("status", ""),
                severity=t.get("severity", ""),
                similarity_score=t.get("similarity_score"),
                similarity_label=t.get("similarity_label", ""),
                similarity_reason=t.get("similarity_reason", ""),
            )
            db.add(mapping)
    await db.commit()


async def get_tickets_in_group(db: AsyncSession,
                                group_id: str) -> list[BugGroupMapping]:
    result = await db.execute(
        select(BugGroupMapping)
        .where(BugGroupMapping.group_id == group_id)
    )
    return list(result.scalars().all())


def _ticket_ref(ticket: dict, role: str) -> dict:
    return {
        "ticket_id": (
            ticket.get("ticket_id")
            or ticket.get("id")
            or ticket.get("key")
            or ""
        ),
        "source_id": (
            ticket.get("source_id")
            or ticket.get("source")
            or ticket.get("system_type")
            or ""
        ),
        "system_type": (
            ticket.get("system_type")
            or ticket.get("source")
            or ""
        ),
        "role": role,
        "title": ticket.get("title", ""),
        "url": ticket.get("url", ""),
        "status": ticket.get("status", ""),
        "severity": ticket.get("severity", ""),
        "similarity_score": ticket.get("similarity_score"),
        "similarity_label": ticket.get("similarity_label", ""),
        "similarity_reason": ticket.get("similarity_reason", ""),
    }


async def persist_related_issue_group(
        db: AsyncSession,
        primary_ticket: dict,
        related_tickets: list[dict]) -> str | None:
    if not primary_ticket or not primary_ticket.get("ticket_id"):
        return None

    root_ref = _ticket_ref(primary_ticket, role="root")
    child_refs = [
        _ticket_ref(ticket, role="child")
        for ticket in (related_tickets or [])
        if (ticket.get("similarity_score")
            or ticket.get("relevance_score")
            or 0) >= 0.50
    ]
    for child in child_refs:
        if child.get("similarity_score") is None:
            child["similarity_score"] = next(
                (
                    ticket.get("relevance_score")
                    for ticket in related_tickets
                    if ((ticket.get("ticket_id")
                         or ticket.get("id")
                         or ticket.get("key")
                         or "") == child["ticket_id"])
                ),
                None,
            )

    tickets = [root_ref] + [
        child for child in child_refs
        if child.get("ticket_id") and child.get("ticket_id") != root_ref["ticket_id"]
    ]
    if len(tickets) <= 1:
        return None

    group_id = await get_group_for_any_ticket(db, tickets)
    if not group_id:
        group_id = await get_next_group_id(db)
        await create_group(
            db,
            group_id,
            primary_ticket.get("title", "Bug Group")[:300],
            primary_ticket.get("severity", "Unknown"),
            primary_ticket.get("source_id", ""),
        )

    for ticket in tickets:
        existing = await get_group_for_ticket(
            db,
            ticket.get("ticket_id", ""),
            ticket.get("source_id", ""),
        )
        if existing:
            await db.execute(
                update(BugGroupMapping)
                .where(
                    BugGroupMapping.raw_ticket_id == ticket.get("ticket_id", ""),
                    BugGroupMapping.source_id == ticket.get("source_id", ""),
                )
                .values(
                    group_id=group_id,
                    role=ticket.get("role", "child"),
                    system_type=ticket.get("system_type", ""),
                    title=ticket.get("title", ""),
                    url=ticket.get("url", ""),
                    status=ticket.get("status", ""),
                    severity=ticket.get("severity", ""),
                    similarity_score=ticket.get("similarity_score"),
                    similarity_label=ticket.get("similarity_label", ""),
                    similarity_reason=ticket.get("similarity_reason", ""),
                )
            )
            continue

        db.add(BugGroupMapping(
            group_id=group_id,
            raw_ticket_id=ticket.get("ticket_id", ""),
            source_id=ticket.get("source_id", ""),
            system_type=ticket.get("system_type", ""),
            role=ticket.get("role", "child"),
            title=ticket.get("title", ""),
            url=ticket.get("url", ""),
            status=ticket.get("status", ""),
            severity=ticket.get("severity", ""),
            similarity_score=ticket.get("similarity_score"),
            similarity_label=ticket.get("similarity_label", ""),
            similarity_reason=ticket.get("similarity_reason", ""),
        ))

    await db.commit()
    return group_id
