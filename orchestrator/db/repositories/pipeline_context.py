from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import PipelineContext

PIPELINE_STEPS = [
    "start",
    "context_fetch",
    "cross_system_fetch",
    "enrichment",
    "ai_synthesis",
    "done",
]


async def create_pipeline_context(db: AsyncSession, case_id: str, context_json: dict | None = None) -> PipelineContext:
    ctx = PipelineContext(case_id=case_id, current_step="start", context_json=context_json or {})
    db.add(ctx)
    await db.commit()
    await db.refresh(ctx)
    return ctx


async def get_pipeline_context(db: AsyncSession, case_id: str) -> PipelineContext | None:
    result = await db.execute(select(PipelineContext).where(PipelineContext.case_id == case_id))
    return result.scalar_one_or_none()


async def update_pipeline_step(db: AsyncSession, case_id: str, step: str, context_json: dict | None = None) -> None:
    values = {"current_step": step}
    if context_json is not None:
        values["context_json"] = context_json
    await db.execute(
        update(PipelineContext).where(PipelineContext.case_id == case_id).values(**values)
    )
    await db.commit()


async def delete_pipeline_context(db: AsyncSession, case_id: str) -> None:
    await db.execute(delete(PipelineContext).where(PipelineContext.case_id == case_id))
    await db.commit()


def get_steps_to_run(from_step: str) -> list[str]:
    try:
        idx = PIPELINE_STEPS.index(from_step)
    except ValueError:
        idx = 0
    return PIPELINE_STEPS[idx + 1:]
