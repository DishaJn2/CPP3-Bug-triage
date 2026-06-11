from fastapi import HTTPException

from orchestrator.db.repositories.user_roles import (
    create_user as create_user_repo,
    delete_user as delete_user_repo,
    get_user_by_email,
    list_users as list_users_repo,
)
from orchestrator.db.session import AsyncSessionLocal


async def list_users() -> list:
    async with AsyncSessionLocal() as db:
        users = await list_users_repo(db)
    return [
        {
            "user_id": u.user_id,
            "role": u.role,
            "display_name": u.display_name or "",
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }
        for u in users
    ]


async def create_user(
    email: str,
    password: str,
    role: str,
    display_name: str,
) -> dict:
    async with AsyncSessionLocal() as db:
        existing = await get_user_by_email(db, email)
        if existing:
            raise HTTPException(status_code=409, detail="User already exists")
        user = await create_user_repo(db, email, password, role, display_name)
        await db.commit()
    return {"user_id": user.user_id, "role": user.role, "display_name": user.display_name or ""}


async def delete_user(email: str) -> dict:
    async with AsyncSessionLocal() as db:
        deleted = await delete_user_repo(db, email)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")
        await db.commit()
    return {"deleted": email}
