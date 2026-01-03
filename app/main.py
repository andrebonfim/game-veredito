from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.routers import home

# Initialize FastAPI App
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-powered Steam review analyzer and price tracker.",
)

# Connect the Limiter to the App
app.state.limiter = limiter


# Define a Custom Error Handler (Fixes the Typing Error)
# Instead of using the default JSON handler, is defined a function
# that returns HTML. This pleases both the Type Checker and HTMX.
def custom_rate_limit_handler(request: Request, exc: Exception):
    """
    This function runs automatically when a user exceeds the limit.
    It returns a formatted HTML alert instead of a generic server error.
    """
    return HTMLResponse(
        content="""
        <div class="p-4 mb-4 text-sm text-yellow-400 bg-yellow-900/20 rounded-lg border border-yellow-900 animate-pulse">
            <span class="font-bold">Calma aí, apressadinho!</span> ✋<br>
            Você fez muitas requisições. Espere um minuto e tente de novo.
        </div>
        """,
        status_code=200,
    )


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
