import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.components.renderer import render_analysis_card, render_error_simple
from app.core.database import load_analysis_by_id
from app.core.limiter import limiter
from app.services.game_service import (
    extract_app_id,
    game_cache,
    get_history,
    prepare_analysis_stream,
    stream_game_analysis,
)

_STALE_THRESHOLD = timedelta(hours=24)

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_valid_steam_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and (
            parsed.netloc == "store.steampowered.com"
            or parsed.netloc.endswith(".steampowered.com")
        )
    except Exception:
        return False


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request, prefill: str = ""):
    return templates.TemplateResponse("index.html", {"request": request, "prefill_url": prefill})


@router.get("/app/{app_id}", response_class=HTMLResponse)
async def game_page(request: Request, app_id: str):
    game_data = game_cache.get(app_id) or load_analysis_by_id(app_id)
    if game_data:
        age = datetime.now(timezone.utc) - game_data.analyzed_at
        stale = age > _STALE_THRESHOLD
        if stale:
            game_cache.pop(app_id, None)
        return templates.TemplateResponse(
            "app_analysis.html",
            {
                "request": request,
                "game": game_data.model_copy(update={"cached": True}).model_dump(mode="json"),
                "stale": stale,
            },
        )
    prefill = f"https://store.steampowered.com/app/{app_id}/"
    return RedirectResponse(url=f"/?prefill={prefill}", status_code=302)


@router.get("/api/reanalyze/{app_id}", response_class=HTMLResponse)
async def reanalyze_endpoint(request: Request, app_id: str):
    game_data = game_cache.get(app_id) or load_analysis_by_id(app_id)
    if not game_data:
        return HTMLResponse(
            render_error_simple(error_type="invalid_url", message="Jogo não encontrado no histórico."),
            status_code=404,
        )
    steam_url = game_data.steam_url
    game_cache.pop(app_id, None)
    log.info("Forced reanalysis for app_id=%s", app_id)
    result = await prepare_analysis_stream(steam_url)
    if isinstance(result, str):
        return HTMLResponse(result)
    _, skeleton_html = result
    return HTMLResponse(skeleton_html)


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    history = [
        {
            "app_id": g.app_id,
            "title": g.title,
            "price": g.price,
            "image_url": g.image_url,
            "verdict": g.analysis.verdict.value,
            "verdict_color": g.analysis.verdict_color,
            "analyzed_at": g.analyzed_at.strftime("%d/%m %H:%M"),
        }
        for g in get_history()
    ]
    return templates.TemplateResponse("history.html", {"request": request, "history": history})


@router.post("/api/analyze", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def analyze_game_endpoint(request: Request, game_url: str = Form(...)):
    if not game_url or not _is_valid_steam_url(game_url):
        log.info("Rejected invalid URL: %.100s", game_url)
        return render_error_simple(
            error_type="invalid_url",
            message="URL Inválida! Por favor, cole um link válido da loja Steam.",
            details="Exemplo: https://store.steampowered.com/app/1091500/Cyberpunk_2077/",
        )

    app_id = extract_app_id(game_url)

    # Cache hit → return full card immediately, no streaming needed
    if app_id and app_id in game_cache:
        log.info("Cache hit for app_id=%s", app_id)
        return render_analysis_card(game_cache[app_id].model_copy(update={"cached": True}))

    # Cache miss → gather Steam data and return skeleton; Gemini runs via SSE
    result = await prepare_analysis_stream(game_url)
    if isinstance(result, str):
        return HTMLResponse(result)
    _stream_id, skeleton_html = result
    return HTMLResponse(skeleton_html)


@router.get("/api/stream/{stream_id}")
async def stream_endpoint(stream_id: str):
    return StreamingResponse(
        stream_game_analysis(stream_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
