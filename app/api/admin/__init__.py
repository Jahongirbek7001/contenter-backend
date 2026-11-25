from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.customers import router as customers_router
from app.api.admin.generations import router as generations_router
from app.api.admin.trends import router as trends_router

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(auth_router)
router.include_router(trends_router)
router.include_router(customers_router)
router.include_router(generations_router)
