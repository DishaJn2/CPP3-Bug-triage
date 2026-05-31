from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ..auth import authenticate_user, create_access_token, get_current_user, require_role, User
from orchestrator.db.session import AsyncSessionLocal
from orchestrator.db.repositories.user_roles import (
    get_user_by_email,
    create_user as create_user_repo,
    list_users as list_users_repo,
    delete_user as delete_user_repo,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    user_id: str
    display_name: str = ""


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str
    display_name: str = ""


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user = await authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token({
        "sub": user.email,
        "role": user.role,
        "display_name": user.display_name,
    })
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        user_id=user.user_id,
        display_name=user.display_name,
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
    }


@router.get("/users", dependencies=[Depends(require_role("admin"))])
async def list_users():
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


@router.post("/users", dependencies=[Depends(require_role("admin"))])
async def create_user(body: CreateUserRequest):
    async with AsyncSessionLocal() as db:
        existing = await get_user_by_email(db, body.email)
        if existing:
            raise HTTPException(status_code=409, detail="User already exists")
        user = await create_user_repo(db, body.email, body.password, body.role, body.display_name)
        await db.commit()
    return {"user_id": user.user_id, "role": user.role, "display_name": user.display_name or ""}


@router.delete("/users/{email}", dependencies=[Depends(require_role("admin"))])
async def delete_user(email: str):
    async with AsyncSessionLocal() as db:
        deleted = await delete_user_repo(db, email)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")
        await db.commit()
    return {"deleted": email}
