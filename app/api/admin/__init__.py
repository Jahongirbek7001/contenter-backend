from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.bonuses import router as bonuses_router
from app.api.admin.catalog import router as catalog_router
from app.api.admin.customers import router as customers_router
from app.api.admin.dashboard import router as dashboard_router
from app.api.admin.generations import router as generations_router
from app.api.admin.promo import router as promo_router
from app.api.admin.trends import router as trends_router

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(auth_router)
router.include_router(trends_router)
router.include_router(customers_router)
router.include_router(generations_router)
router.include_router(promo_router)
router.include_router(bonuses_router)
router.include_router(dashboard_router)
router.include_router(catalog_router)
