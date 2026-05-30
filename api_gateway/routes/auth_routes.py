from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ..auth import authenticate_user, create_access_token, get_current_user, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    user_id: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user = authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token({"sub": user.email, "role": user.role})
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        user_id=user.user_id,
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"user_id": user.user_id, "email": user.email, "role": user.role}
