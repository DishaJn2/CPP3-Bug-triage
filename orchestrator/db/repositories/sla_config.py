from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SLAConfig


async def upsert_sla_config(db: AsyncSession, data: dict) -> SLAConfig:
    stmt = insert(SLAConfig).values(**data)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tier_name"],
        set_={k: v for k, v in data.items() if k != "tier_name"},
    )
    await db.execute(stmt)
    await db.commit()
    result = await db.execute(select(SLAConfig).where(SLAConfig.tier_name == data["tier_name"]))
    return result.scalar_one()


async def get_sla_config(db: AsyncSession, tier_name: str) -> SLAConfig | None:
    result = await db.execute(select(SLAConfig).where(SLAConfig.tier_name == tier_name))
    return result.scalar_one_or_none()
