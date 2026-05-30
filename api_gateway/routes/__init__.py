from .auth_routes import router as auth_router
from .cases_routes import router as cases_router
from .triage_routes import router as triage_router
from .settings_routes import router as settings_router

__all__ = ["auth_router", "cases_router", "triage_router", "settings_router"]
