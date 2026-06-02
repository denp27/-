from app.handlers.start import router as start_router
from app.handlers.stars import router as stars_router
from app.handlers.ton import router as ton_router
from app.handlers.premium import router as premium_router
from app.handlers.profile import router as profile_router
from app.handlers.nft import router as nft_router
from app.handlers.numbers import router as numbers_router
from app.handlers.deposit import router as deposit_router
from app.handlers.admin import router as admin_router
from app.handlers.franchise import router as franchise_router
from app.handlers.checks import router as checks_router
from app.handlers.history import router as history_router

__all__ = [
    "start_router",
    "stars_router",
    "ton_router",
    "premium_router",
    "profile_router",
    "nft_router",
    "numbers_router",
    "deposit_router",
    "admin_router",
    "franchise_router",
    "checks_router",
    "history_router",
]
