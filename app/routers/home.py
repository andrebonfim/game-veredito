from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.game_service import generate_game_analysis

router = APIRouter()

# Setup Jinja2 templates directory
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """
    Renders the landing page.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/api/analyze", response_class=HTMLResponse)
async def analyze_game_endpoint(request: Request, game_url: str = Form(...)):
    """
    HTMX Endpoint.
    Receives the game URL, processes logic (mocked for now), and returns HTML snippet.
    """

    # 1. Input Validation (Basic)
    if not game_url or "steampowered.com" not in game_url:
        return """
        <div class="p-4 mb-4 text-sm text-red-400 bg-red-900/20 rounded-lg border border-red-900 animate-fade-in" role="alert">
            <span class="font-bold">URL Inválida!</span> Por favor, cole um link válido da loja Steam.
        </div>
        """

    # 2. Call IA service to generate analysis
    ai_html_response = await generate_game_analysis(game_url)

    return ai_html_response
