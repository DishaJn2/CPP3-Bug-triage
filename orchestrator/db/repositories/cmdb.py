from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import CMDBTeamRegistry


async def get_all_cmdb_entries(db: AsyncSession) -> list[CMDBTeamRegistry]:
    result = await db.execute(select(CMDBTeamRegistry))
    return list(result.scalars().all())


async def create_cmdb_entry(db: AsyncSession, data: dict) -> CMDBTeamRegistry:
    entry = CMDBTeamRegistry(**data)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_cmdb_entry_by_component(db: AsyncSession, component_name: str) -> CMDBTeamRegistry | None:
    result = await db.execute(
        select(CMDBTeamRegistry).where(CMDBTeamRegistry.component_name == component_name)
    )
    return result.scalar_one_or_none()
