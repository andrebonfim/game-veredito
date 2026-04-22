from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.components.renderer import render_error_simple
from app.core.config import settings
from app.core.database import init_db, load_all_analyses
from app.core.limiter import limiter
from app.routers import home
from app.services.game_service import game_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    loaded = 0
    for game_data in load_all_analyses():
        if game_data.app_id not in game_cache:
            game_cache[game_data.app_id] = game_data
            loaded += 1
    import logging
    logging.getLogger(__name__).info("Loaded %d analyses from DB into cache", loaded)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Analisador de jogos da Steam com IA e comparador de preços.",
    lifespan=lifespan,
)

app.state.limiter = limiter


def custom_rate_limit_handler(request: Request, exc: Exception):
    html_content = render_error_simple(
        error_type="rate_limit",
        message="Calma aí! ✋ Você fez muitas requisições.",
        details="Espere um minuto e tente novamente.",
    )
    return HTMLResponse(content=html_content, status_code=200)


app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(home.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
