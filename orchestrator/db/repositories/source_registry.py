from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SourceRegistry


async def get_all_sources(db: AsyncSession) -> list[SourceRegistry]:
    result = await db.execute(select(SourceRegistry))
    return list(result.scalars().all())


async def get_enabled_sources(db: AsyncSession) -> list[SourceRegistry]:
    result = await db.execute(select(SourceRegistry).where(SourceRegistry.enabled == True))
    return list(result.scalars().all())


async def get_source_by_id(db: AsyncSession, source_id: str) -> SourceRegistry | None:
    result = await db.execute(select(SourceRegistry).where(SourceRegistry.source_id == source_id))
    return result.scalar_one_or_none()


async def create_source(db: AsyncSession, data: dict) -> SourceRegistry:
    source = SourceRegistry(**data)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def update_source(db: AsyncSession, source_id: str, data: dict) -> SourceRegistry | None:
    await db.execute(
        update(SourceRegistry).where(SourceRegistry.source_id == source_id).values(**data)
    )
    await db.commit()
    return await get_source_by_id(db, source_id)


async def set_source_enabled(db: AsyncSession, source_id: str, enabled: bool) -> None:
    await db.execute(
        update(SourceRegistry).where(SourceRegistry.source_id == source_id).values(enabled=enabled)
    )
    await db.commit()
