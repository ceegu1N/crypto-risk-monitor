from pathlib import Path

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.config import Settings
from app.db import create_database_engine

WEB_ROOT = Path(__file__).parent / "web"


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    current_settings = settings or Settings()  # type: ignore[call-arg]
    current_settings.validate_web_security()
    current_factory = session_factory or sessionmaker(
        bind=create_database_engine(current_settings.database_url),
        expire_on_commit=False,
    )
    app = FastAPI(
        title="Crypto Market & Portfolio Risk Monitor",
        version="0.1.0",
        description=(
            "Monitor explicável de mercado; não executa ordens nem recomenda investimentos."
        ),
    )
    app.state.settings = current_settings
    app.state.session_factory = current_factory
    app.add_middleware(
        SessionMiddleware,
        secret_key=current_settings.session_secret,
        session_cookie=(
            "__Host-crypto_risk_session"
            if current_settings.session_cookie_secure
            else "crypto_risk_session"
        ),
        max_age=8 * 60 * 60,
        same_site="strict",
        https_only=current_settings.session_cookie_secure,
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "font-src 'none'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
        if current_settings.session_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    templates = Jinja2Templates(directory=WEB_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="index.html")

    app.include_router(router)
    return app
