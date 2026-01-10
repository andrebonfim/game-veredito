"""
Main Application Module

This is the entry point of the FastAPI application.
It configures:
- FastAPI app instance
- Rate limiting (prevents API abuse)
- Static files (CSS, images)
- Route handlers

ARCHITECTURE OVERVIEW:
┌─────────────────────────────────────────────────────────────┐
│                         main.py                              │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │   Limiter   │  │   Routers    │  │   Static Files    │   │
│  └──────┬──────┘  └──────┬───────┘  └─────────┬─────────┘   │
│         │                │                    │              │
│         ▼                ▼                    ▼              │
│  Rate Limiting      /api/analyze         /static/*          │
│  5 req/min          Game Analysis        CSS, Images        │
└─────────────────────────────────────────────────────────────┘
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.components.renderer import render_error_simple
from app.core.config import settings
from app.core.limiter import limiter
from app.routers import home

# Initialize FastAPI App
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Analisador de jogos da Steam com IA e comparador de preços.",
)

# Connect the Limiter to the App
# This enables rate limiting across all routes
app.state.limiter = limiter


def custom_rate_limit_handler(request: Request, exc: Exception):
    """
    Custom handler for rate limit exceeded errors.

    WHY CUSTOM HANDLER?
    - Default SlowAPI returns JSON error, but we use HTMX
    - HTMX expects HTML fragments
    - This returns a styled error that matches our UI

    WHEN IS THIS CALLED?
    - When a user makes more than 5 requests per minute
    - SlowAPI automatically triggers this handler
    """
    html_content = render_error_simple(
        error_type="rate_limit",
        message="Calma aí! ✋ Você fez muitas requisições.",
        details="Espere um minuto e tente novamente.",
    )
    return HTMLResponse(content=html_content, status_code=200)


# Add the exception handler to the app
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

# Mount static files folder (CSS, Images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include organized routes
app.include_router(home.router)

if __name__ == "__main__":
    import uvicorn

    # Run server with auto-reload enabled for development
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
