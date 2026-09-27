"""Aggregates all /api/v1 routers."""

from fastapi import APIRouter

from app.api.v1 import auth, documents, retrieval

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(retrieval.router)
