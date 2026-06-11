from fastapi import HTTPException, status

from ..auth import authenticate_user, create_access_token


async def login(email: str, password: str) -> dict:
    user = await authenticate_user(email, password)
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
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.user_id,
        "display_name": user.display_name,
    }
