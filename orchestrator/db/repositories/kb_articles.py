from sqlalchemy import Text, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from orchestrator.db.models import KBArticle


async def search_kb_articles(session: AsyncSession, query: str, limit: int = 5) -> list[KBArticle]:
    q = query.lower()
    result = await session.execute(
        select(KBArticle).where(
            or_(
                KBArticle.title.ilike(f"%{q}%"),
                KBArticle.content.ilike(f"%{q}%"),
                KBArticle.tags.cast(Text).ilike(f"%{q}%"),
            )
        ).limit(limit)
    )
    return list(result.scalars().all())


async def get_all_kb_articles(session: AsyncSession) -> list[KBArticle]:
    result = await session.execute(select(KBArticle))
    return list(result.scalars().all())


async def insert_kb_article(session: AsyncSession, data: dict) -> KBArticle | None:
    existing = await session.execute(select(KBArticle).where(KBArticle.article_id == data["article_id"]))
    if existing.scalar_one_or_none():
        return None
    article = KBArticle(**data)
    session.add(article)
    await session.flush()
    return article
