"""Aggregates all v1 routers. Routes stay thin: they orchestrate services only."""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
