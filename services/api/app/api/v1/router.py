"""Aggregates all v1 routers. Routes stay thin: they orchestrate services only."""

from fastapi import APIRouter

from app.api.v1 import analysis, auth, files, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(files.router, tags=["files"])
api_router.include_router(analysis.router, tags=["analysis"])
