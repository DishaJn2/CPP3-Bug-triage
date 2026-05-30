from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import AuditLog


async def insert_audit_entry(db: AsyncSession, data: dict) -> AuditLog:
    entry = AuditLog(**data)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_last_triage_for_bug(db: AsyncSession, bug_id: str) -> AuditLog | None:
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.bug_id == bug_id, AuditLog.step == "pipeline_complete")
        .order_by(desc(AuditLog.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_metrics_summary(db: AsyncSession) -> dict:
    total = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.step == "pipeline_complete")
    )
    total_count = total.scalar() or 0

    return {
        "total_triaged": total_count,
    }


async def list_recent_pipeline_completions(db: AsyncSession, limit: int = 50) -> list[AuditLog]:
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.step == "pipeline_complete")
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())
