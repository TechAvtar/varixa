from fastapi import APIRouter, status

from app.api.deps import AuthSvc, ClientIp, CurrentSessionId, CurrentUser
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, auth: AuthSvc, client_ip: ClientIp) -> UserResponse:
    user = await auth.register(
        email=body.email, password=body.password, name=body.name, client_ip=client_ip
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, auth: AuthSvc, client_ip: ClientIp) -> TokenPair:
    tokens = await auth.login(email=body.email, password=body.password, client_ip=client_ip)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, auth: AuthSvc) -> TokenPair:
    tokens = await auth.refresh(refresh_token=body.refresh_token)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_: CurrentUser, session_id: CurrentSessionId, auth: AuthSvc) -> None:
    await auth.logout(session_id=session_id)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
