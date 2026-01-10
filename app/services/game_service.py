"""
Game Service Module

This is the main "brain" of the application. It orchestrates:
1. Fetching data from Steam (API + Web Scraping)
2. Calling the Gemini AI for analysis
3. Parsing AI response into structured JSON
4. Caching results to save API calls

KEY CHANGE IN THIS REFACTOR:
- BEFORE: AI generated HTML directly (inconsistent design)
- AFTER: AI returns JSON, we parse it, then render with fixed templates

WHY JSON INSTEAD OF HTML?
1. Consistency: The layout is always the same, defined by our templates
2. Validation: We can check if the AI returned valid data
3. Caching: JSON is smaller and easier to cache than HTML
4. Flexibility: Same JSON can be rendered differently (web, mobile, etc.)
"""

import json
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from cachetools import TTLCache
from google import genai
from pydantic import ValidationError

from app.components.renderer import render_analysis_card, render_error_simple
from app.core.config import settings
from app.schemas.game import GameAnalysis, GameData

# Instantiate Gemini Client
# This creates the connection to Google's AI service
client = genai.Client(api_key=settings.GEMINI_API_KEY)

# --- CACHE CONFIGURATION (MEMORY) ---
# maxsize=100: Stores the last 100 queried games
# ttl=86400: Expires data after 24 hours (86400 seconds) to update prices
#
# HOW CACHE WORKS:
# - First request for a game: Fetch from Steam + AI, save to cache
# - Second request for same game: Return cached data instantly
# - After 24 hours: Cache expires, next request fetches fresh data
game_cache: TTLCache[str, GameData] = TTLCache(maxsize=100, ttl=86400)


def extract_app_id(url: str):
    """
    Extracts the numeric App ID from the Steam URL.
    Example: .../app/1091500/Cyberpunk -> Returns '1091500'
    """
    match = re.search(r"/app/(\d+)", url)
    return match.group(1) if match else None


def get_steam_api_data(app_id: str):
    """
    Fetch Price (R$) and Cover Image from the Steam API.
    Returns a dict: {'price': str, 'image': str}
    """
    try:
        # 'cc=br' forces the currency to Brazilian Real
        # 'l=brazilian' ensures localized text if needed
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&l=brazilian"
        response = requests.get(url, timeout=5)
        data = response.json()

        # Check if API response is valid and successful
        if not data or not data.get(app_id) or not data[app_id]["success"]:
            return {"price": "Preço indisponível", "image": ""}

        game_data = data[app_id]["data"]

        # 1. Fetch Image
        image_url = game_data.get("header_image", "")

        # 2. Fetch Price
        price_text = "Não listado"
        if game_data.get("is_free"):
            price_text = "Gratuito (Free to Play)"
        elif game_data.get("price_overview"):
            price_overview = game_data.get("price_overview")
            final_price = price_overview.get("final_formatted")
            discount = price_overview.get("discount_percent", 0)
            if discount > 0:
                price_text = f"{final_price} (-{discount}%)"
            else:
                price_text = final_price

        return {"price": price_text, "image": image_url}

    except Exception as e:
        print(f"Error fetching API data: {e}")
        return {"price": "Erro", "image": ""}


def get_steam_reviews(app_id: str):
    """
    NEW: Fetches the top 10 most useful reviews (Positive & Negative) from Steam API.
    This gives the AI the 'real user opinion' regarding bugs and performance.
    """
    try:
        # filter=summary: Gets the most relevant/useful
        # language=all: Gets English and Portuguese (English usually has more tech analysis)
        url = f"https://store.steampowered.com/appreviews/{app_id}?json=1&filter=summary&language=all&num_per_page=10&purchase_type=all"

        response = requests.get(url, timeout=5)
        data = response.json()

        if not data or "reviews" not in data:
            return "Não foi possível ler os reviews dos usuários."

        reviews_list = []
        for review in data["reviews"]:
            # Clean text and limit length to avoid token overflow
            text = review.get("review", "").replace("\n", " ")[:500]
            votes = review.get("votes_up", 0)
            reviews_list.append(f"- (👍 {votes} votos): {text}")

        return "\n".join(reviews_list)

    except Exception as e:
        print(f"Error fetching reviews: {e}")
        return "Erro ao buscar reviews."


def get_steam_store_text(url: str):
    """
    Scrapes the Steam store page to get the DESCRIPTION (Marketing text).
    Renamed from 'get_steam_text' to be more specific.
    """
    try:
        # Cookies to bypass Steam's age verification gate (Age Gate)
        cookies = {"birthtime": "568022401", "lastagecheckage": "1-January-1988"}

        # Timeout set to 10s to avoid hanging
        response = requests.get(url, cookies=cookies, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract game title
        game_title = soup.find("div", {"id": "appHubAppName"})
        game_title = game_title.text.strip() if game_title else "Jogo Desconhecido"

        # Refined: Try to get specific description div first
        description = soup.find("div", {"id": "game_area_description"})
        if description:
            raw_text = description.get_text(separator=" ", strip=True)[:10000]
        else:
            # Fallback to whole body if description div is missing
            raw_text = soup.get_text(separator=" ", strip=True)[:10000]

        return game_title, raw_text

    except Exception:
        return None, None


def parse_ai_json_response(response_text: str) -> Optional[GameAnalysis]:
    """
    Parses the AI response text into a GameAnalysis object.

    WHY THIS FUNCTION EXISTS:
    - The AI might return JSON with markdown code blocks (```json ... ```)
    - The AI might return invalid JSON sometimes
    - We need to handle these cases gracefully

    STEPS:
    1. Try to extract JSON from markdown code blocks
    2. Parse the JSON string
    3. Validate with Pydantic schema
    4. Return None if anything fails
    """
    try:
        # Remove markdown code blocks if present
        # AI often returns: ```json\n{...}\n```
        text = response_text.strip()

        if text.startswith("```"):
            # Find the actual JSON content between the code blocks
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```") and not in_json:
                    in_json = True
                    continue
                elif line.startswith("```") and in_json:
                    break
                elif in_json:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        # Parse JSON string into Python dict
        data = json.loads(text)

        # Validate with Pydantic (this ensures all required fields exist)
        analysis = GameAnalysis(**data)

        return analysis

    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}")
        print(f"Raw response: {response_text[:500]}...")
        return None
    except ValidationError as e:
        print(f"Pydantic Validation Error: {e}")
        return None


def build_json_prompt(
    title: str, price_brl: str, store_text: str, user_reviews: str
) -> str:
    """
    Builds the prompt for the AI to generate a JSON analysis.

    KEY CHANGES FROM OLD PROMPT:
    - No more HTML template in the prompt
    - AI returns structured JSON
    - Same analysis quality, different output format

    The prompt structure is kept similar to maintain analysis quality.
    """
    return f"""
Você é um crítico de games brasileiro, especialista em Custo-Benefício e Performance Técnica no PC.
Analise o jogo "{title}".

PREÇO ATUAL NO BRASIL: {price_brl}

O QUE A DESENVOLVEDORA DIZ (Marketing):
{store_text}

O QUE OS JOGADORES DIZEM (Reviews Reais - Importante para detectar bugs/performance):
{user_reviews}

INSTRUÇÕES:
1. Analise o jogo considerando preço, qualidade e performance técnica.
2. Escolha um veredito: "COMPRAR AGORA" (verde), "ESPERAR PROMOÇÃO" (amarelo), ou "FUGIR" (vermelho).
3. Use o preço ({price_brl}) para decidir. Se for caro e tiver problemas técnicos, recomende esperar.
4. Responda APENAS com JSON válido, sem markdown, sem explicações extras.

FORMATO DE RESPOSTA (JSON):
{{
    "verdict": "COMPRAR AGORA" | "ESPERAR PROMOÇÃO" | "FUGIR",
    "verdict_color": "green" | "yellow" | "red",
    "analysis_text": "Sua análise detalhada aqui. Mencione o preço e se vale a pena. Mínimo 100 palavras.",
    "positive_points": ["Ponto positivo 1", "Ponto positivo 2", "Ponto positivo 3"],
    "negative_points": ["Ponto negativo 1", "Ponto negativo 2"],
    "performance_notes": ["Nota sobre FPS/bugs", "Requisitos de hardware"]
}}

REGRAS DO JSON:
- verdict: EXATAMENTE um dos três valores
- verdict_color: "green" para COMPRAR, "yellow" para ESPERAR, "red" para FUGIR
- analysis_text: Texto corrido, mínimo 100 palavras, em português brasileiro
- positive_points: Lista de 1 a 5 strings
- negative_points: Lista de 0 a 5 strings (pode ser vazia se o jogo for perfeito)
- performance_notes: Lista de 1 a 3 strings sobre performance técnica

Responda APENAS com o JSON, nada mais.
"""


async def generate_game_analysis(game_url: str) -> str:
    """
    Main Orchestrator Function.

    This is the entry point called by the router. It:
    1. Validates the URL and extracts the App ID
    2. Checks if we have a cached result
    3. Fetches data from Steam (scraping + API)
    4. Calls Gemini AI for analysis
    5. Parses the JSON response
    6. Renders HTML using fixed templates
    7. Caches the result for future requests

    RETURNS:
    - HTML string (rendered from templates, NOT from AI)

    FLOW DIAGRAM:
    URL → Extract ID → Check Cache → Fetch Steam Data → Call AI →
    Parse JSON → Create GameData → Render HTML → Cache → Return
    """

    # STEP 1: Extract App ID from URL
    app_id = extract_app_id(game_url)

    if not app_id:
        return render_error_simple(
            error_type="invalid_url",
            message="Link Inválido! Verifique se a URL é da loja Steam.",
        )

    # STEP 2: Check Cache
    # If we already analyzed this game recently, return cached result
    if app_id in game_cache:
        print(f"⚡ CACHE HIT: Returning saved analysis for ID {app_id}")
        cached_data = game_cache[app_id]
        # Mark as cached so the UI can show a cache badge
        cached_data.cached = True
        return render_analysis_card(cached_data)

    print(f"🔍 CACHE MISS: Analyzing {app_id} for the first time...")

    # STEP 3: Scrape Store Page (Marketing Text)
    title, store_text = get_steam_store_text(game_url)

    if not store_text:
        return render_error_simple(
            error_type="steam_error",
            message="Erro ao acessar a Steam!",
            details="Não consegui ler a página do jogo. Tente novamente em alguns segundos.",
        )

    # STEP 4: Fetch Additional Data from Steam API
    user_reviews = get_steam_reviews(app_id)
    api_data = get_steam_api_data(app_id)
    price_brl = api_data["price"]
    image_url = api_data["image"]

    # STEP 5: Build Prompt and Call Gemini AI
    prompt = build_json_prompt(title, price_brl, store_text, user_reviews)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        raw_response = response.text

        # STEP 6: Parse AI Response into Structured Data
        analysis = parse_ai_json_response(raw_response)

        if analysis is None:
            # AI returned invalid JSON, show error
            return render_error_simple(
                error_type="ai_error",
                message="A IA retornou uma resposta inválida.",
                details="Tente novamente. Se o erro persistir, o jogo pode ter informações muito complexas.",
            )

        # STEP 7: Create Complete GameData Object
        game_data = GameData(
            app_id=app_id,
            title=title,
            price=price_brl,
            image_url=image_url,
            steam_url=game_url,
            analysis=analysis,
            cached=False,
        )

        # STEP 8: Save to Cache (save GameData, not HTML)
        game_cache[app_id] = game_data

        # STEP 9: Render HTML using Fixed Template
        return render_analysis_card(game_data)

    except Exception as e:
        print(f"Error in Gemini: {e}")
        return render_error_simple(
            error_type="ai_error",
            message="Erro ao conectar com a IA!",
            details=f"Detalhes técnicos: {str(e)}",
        )
