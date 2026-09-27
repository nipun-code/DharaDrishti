from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthServiceDep, CurrentUserDep, enforce_auth_rate_limit
from app.core.security import TokenPair
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from app.schemas.error import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
}
_LIMITED = [Depends(enforce_auth_rate_limit)]


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=_LIMITED,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(body: RegisterRequest, auth: AuthServiceDep) -> UserRead:
    user = await auth.register(body.email, body.password)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse, responses=_UNAUTHORIZED, dependencies=_LIMITED)
async def login(body: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    return _tokens(await auth.login(body.email, body.password))


@router.post(
    "/refresh", response_model=TokenResponse, responses=_UNAUTHORIZED, dependencies=_LIMITED
)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenResponse:
    return _tokens(await auth.refresh(body.refresh_token))


@router.get("/me", response_model=UserRead, responses=_UNAUTHORIZED)
async def me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)
