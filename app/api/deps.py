from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_db
from app.models import ApiToken, User
from app.security import hash_token

DB = Annotated[AsyncSession, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_token(
    db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> ApiToken:
    """The ApiToken for this request's bearer token, with its user loaded. 401 if missing or
    unknown (Laravel's message, so the frontend sees the same thing as before)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthenticated.")
    token = await db.scalar(
        select(ApiToken)
        .where(ApiToken.token_hash == hash_token(credentials.credentials))
        .options(joinedload(ApiToken.user))
    )
    if token is None:
        raise HTTPException(status_code=401, detail="Unauthenticated.")

    token.last_used_at = datetime.now(UTC)
    await db.commit()
    return token


async def get_current_user(token: Annotated[ApiToken, Depends(get_current_token)]) -> User:
    return token.user


CurrentToken = Annotated[ApiToken, Depends(get_current_token)]
CurrentUser = Annotated[User, Depends(get_current_user)]
