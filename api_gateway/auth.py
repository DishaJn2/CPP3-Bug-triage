from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class User:
    user_id: str
    email: str
    role: str
    display_name: str = ""


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def authenticate_user(email: str, password: str) -> Optional[User]:
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.repositories.user_roles import get_user_by_email

    async with AsyncSessionLocal() as db:
        user_record = await get_user_by_email(db, email)

    if not user_record:
        return None
    if not pwd_context.verify(password, user_record.password_hash):
        return None
    return User(
        user_id=user_record.user_id,
        email=user_record.user_id,
        role=user_record.role,
        display_name=user_record.display_name or email.split("@")[0],
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub", "")
        role: str = payload.get("role", "")
        display_name: str = payload.get("display_name", "")
        if not email:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return User(user_id=email, email=email, role=role, display_name=display_name)


def require_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _check
