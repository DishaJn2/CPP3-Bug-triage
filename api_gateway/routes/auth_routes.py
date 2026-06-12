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
from ..services import auth_service, user_service

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
    return await auth_service.login(body.email, body.password)


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
    return await user_service.list_users()


@router.post("/users", dependencies=[Depends(require_role("admin"))])
async def create_user(body: CreateUserRequest):
    return await user_service.create_user(
        email=body.email,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
    )


@router.delete("/users/{email}", dependencies=[Depends(require_role("admin"))])
async def delete_user(email: str):
    return await user_service.delete_user(email)


