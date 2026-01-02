import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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
        <div class="p-4 mb-4 text-sm text-red-400 bg-red-900/20 rounded-lg border border-red-900" role="alert">
            <span class="font-bold">Invalid URL!</span> Please paste a valid Steam store link.
        </div>
        """

    # 2. Simulate Processing Delay (To show the spinner)
    # In production, this will be the API calls to Steam/Gemini
    await asyncio.sleep(1.5)

    # 3. Return the "Verdict Card" (This is pure HTML, no JSON)
    return """
    <div class="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden shadow-2xl animate-fade-in-up">
        <div class="bg-gray-900/50 p-6 border-b border-gray-700 flex justify-between items-center">
            <h2 class="text-2xl font-bold text-white">Cyberpunk 2077 (Simulation)</h2>
            <span class="px-3 py-1 bg-yellow-500/20 text-yellow-400 text-xs font-bold uppercase tracking-wider rounded-full">
                Wait for Sale
            </span>
        </div>
        
        <div class="p-6 space-y-4 text-left">
            <div>
                <h3 class="text-green-400 font-bold text-sm uppercase mb-1">AI Verdict</h3>
                <p class="text-gray-300 leading-relaxed">
                    Recent reviews indicate <span class="text-white font-bold">mixed performance</span> on latest patch. 
                    Story is excellent, but Linux users report some crashes on Proton Experimental.
                </p>
            </div>
            
            <div class="grid grid-cols-2 gap-4 mt-4">
                <div class="bg-gray-900 p-4 rounded-lg">
                    <span class="text-gray-500 text-xs block">Steam Price</span>
                    <span class="text-xl font-mono text-white">R$ 199.90</span>
                </div>
                <div class="bg-green-900/20 p-4 rounded-lg border border-green-900">
                    <span class="text-green-500 text-xs block">Best Price (Nuuvem)</span>
                    <span class="text-xl font-mono text-green-400 font-bold">R$ 99.90</span>
                </div>
            </div>
        </div>
    </div>
    """
