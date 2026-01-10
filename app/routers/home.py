"""
Home Router Module

This module handles the main routes of the application:
- GET /: Renders the landing page
- POST /api/analyze: Receives a Steam URL and returns the analysis

HTMX INTEGRATION:
- The /api/analyze endpoint is called by HTMX when the form is submitted
- It returns HTML fragments that HTMX swaps into the page
- This creates a smooth, SPA-like experience without full page reloads
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.components.renderer import render_error_simple
from app.core.limiter import limiter
from app.services.game_service import generate_game_analysis

router = APIRouter()

# Setup Jinja2 templates directory
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """
    Renders the landing page.

    This is a simple route that just returns the index.html template.
    The template contains the search form and HTMX attributes.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/api/analyze", response_class=HTMLResponse)
@limiter.limit("5/minute")  # Rate limit: 5 requests per minute per IP
async def analyze_game_endpoint(request: Request, game_url: str = Form(...)):
    """
    HTMX Endpoint for game analysis.

    FLOW:
    1. User submits Steam URL via form
    2. HTMX sends POST request to this endpoint
    3. We validate the URL
    4. We call generate_game_analysis() which:
       - Fetches data from Steam
       - Calls Gemini AI for analysis
       - Returns rendered HTML
    5. HTMX swaps the HTML into #result-area

    PARAMETERS:
    - request: FastAPI Request object (needed for rate limiter)
    - game_url: The Steam store URL submitted by user

    RETURNS:
    - HTML fragment (analysis card or error alert)
    """

    # STEP 1: Input Validation
    # Check if URL is present and looks like a Steam URL
    if not game_url or "steampowered.com" not in game_url:
        return render_error_simple(
            error_type="invalid_url",
            message="URL Inválida! Por favor, cole um link válido da loja Steam.",
            details="Exemplo: https://store.steampowered.com/app/1091500/Cyberpunk_2077/",
        )

    # STEP 2: Call the Game Service
    # This is wrapped in try/except to catch any unexpected errors
    try:
        return await generate_game_analysis(game_url)
    except Exception as e:
        # Log the error for debugging
        print(f"Unexpected error in analyze endpoint: {e}")
        return render_error_simple(
            error_type="ai_error",
            message="Erro Interno! Algo deu errado.",
            details="Tente novamente em alguns instantes. Se o erro persistir, contate o suporte.",
        )
