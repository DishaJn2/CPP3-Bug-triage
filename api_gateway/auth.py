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

_DEMO_PLAIN = {
    "disha@hpe.com": {"password": "password123", "role": "engineer"},
    "admin@hpe.com": {"password": "admin123", "role": "admin"},
    "customer@acme.com": {"password": "customer123", "role": "customer"},
}

DEMO_USERS: dict = {}


def _ensure_demo_users():
    if not DEMO_USERS:
        for email, data in _DEMO_PLAIN.items():
            DEMO_USERS[email] = {
                "password_hash": pwd_context.hash(data["password"]),
                "role": data["role"],
            }


@dataclass
class User:
    user_id: str
    email: str
    role: str


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def authenticate_user(email: str, password: str) -> Optional[User]:
    _ensure_demo_users()
    user_data = DEMO_USERS.get(email)
    if not user_data:
        return None
    if not verify_password(password, user_data["password_hash"]):
        return None
    return User(user_id=email, email=email, role=user_data["role"])


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
        if not email:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return User(user_id=email, email=email, role=role)


def require_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return Depends(_check)
