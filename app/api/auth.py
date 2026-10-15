from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentToken
from app.models import ApiToken, User
from app.rate_limit import client_ip, login_limiter
from app.schemas.auth import LoginRequest, LoginResponse, UserOut
from app.security import hash_token, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

BAD_CREDENTIALS = "The credentials you provided are incorrect."


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, db: DB) -> LoginResponse | JSONResponse:
    login_limiter.hit(client_ip(request))

    user = await db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not verify_password(payload.password, user.password_hash if user else None):
        # Same 422 shape the Laravel backend returned.
        return JSONResponse(
            {"message": BAD_CREDENTIALS, "errors": {"email": [BAD_CREDENTIALS]}},
            status_code=422,
        )

    token = new_token()
    db.add(ApiToken(user_id=user.id, token_hash=hash_token(token)))
    await db.commit()
    return LoginResponse(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
async def logout(token: CurrentToken, db: DB) -> Response:
    """Revoke the token used for this request."""
    await db.delete(token)
    await db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(token: CurrentToken) -> UserOut:
    return UserOut.model_validate(token.user)
