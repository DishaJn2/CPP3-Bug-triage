import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/hpe_bugtriage")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from orchestrator.db.base import Base
    import orchestrator.db.models  # noqa: F401 — ensures all models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_bug_group_mapping_columns(conn)


async def ensure_runtime_schema() -> None:
    async with engine.begin() as conn:
        await _ensure_bug_group_mapping_columns(conn)


async def _ensure_bug_group_mapping_columns(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE bug_group_mappings
        ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'child',
        ADD COLUMN IF NOT EXISTS title VARCHAR(500),
        ADD COLUMN IF NOT EXISTS url TEXT,
        ADD COLUMN IF NOT EXISTS status VARCHAR(50),
        ADD COLUMN IF NOT EXISTS severity VARCHAR(50),
        ADD COLUMN IF NOT EXISTS similarity_score DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS similarity_label VARCHAR(100),
        ADD COLUMN IF NOT EXISTS similarity_reason TEXT
    """))
