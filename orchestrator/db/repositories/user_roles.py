from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
from orchestrator.db.models import UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def get_user_by_email(session: AsyncSession, email: str) -> UserRole | None:
    result = await session.execute(
        select(UserRole).where(UserRole.user_id == email)
    )
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    email: str,
    password: str,
    role: str,
    display_name: str = "",
) -> UserRole:
    user = UserRole(
        user_id=email,
        role=role,
        password_hash=pwd_context.hash(password),
        display_name=display_name or email.split("@")[0],
    )
    session.add(user)
    await session.flush()
    return user


async def list_users(session: AsyncSession) -> list[UserRole]:
    result = await session.execute(select(UserRole))
    return list(result.scalars().all())


async def delete_user(session: AsyncSession, email: str) -> bool:
    user = await get_user_by_email(session, email)
    if user:
        await session.delete(user)
        await session.flush()
        return True
    return False
