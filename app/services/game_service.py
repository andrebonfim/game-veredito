import re

import requests
from bs4 import BeautifulSoup
from google import genai

from app.core.config import settings

# Instantiate Gemini Client
client = genai.Client(api_key=settings.GEMINI_API_KEY)


def extract_app_id(url: str):
    """
    Extracts the numeric App ID from the Steam URL.
    Example: .../app/1091500/Cyberpunk -> Returns '1091500'
    """
    match = re.search(r"/app/(\d+)", url)
    return match.group(1) if match else None


def get_steam_price_brl(app_id: str):
    """
    Fetches the official price in BRL (Reais) using Steam API.
    Returns a formatted string (e.g., 'R$ 199,90') or status text in PT-BR.
    """
    try:
        # 'cc=br' forces the currency to Brazilian Real
        # 'l=brazilian' ensures localized text if needed
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&l=brazilian"
        response = requests.get(url, timeout=5)
        data = response.json()

        # Check if API response is valid and successful
        if not data or not data.get(app_id) or not data[app_id]["success"]:
            return "Preço indisponível"

        game_data = data[app_id]["data"]

        # Handle Free to Play games
        if game_data.get("is_free"):
            return "Gratuito (Free to Play)"

        price_overview = game_data.get("price_overview")
        if not price_overview:
            return "Não listado / Não lançado"

        # Extract formatted price (e.g., "R$ 100,00")
        final_price = price_overview.get("final_formatted")
        discount = price_overview.get("discount_percent", 0)

        # If there is a discount, format it for the AI/User
        if discount > 0:
            return f"{final_price} (Com {discount}% de desconto hoje!)"

        return final_price

    except Exception as e:
        print(f"Error fetching price: {e}")
        return "Erro ao consultar preço"


def get_steam_text(url: str):
    """
    Scrapes the Steam store page to get description and reviews summary.
    """
    try:
        # Cookies to bypass Steam's age verification gate (Age Gate)
        cookies = {"birthtime": "568022401", "lastagecheckage": "1-January-1988"}

        # Timeout set to 10s to avoid hanging
        response = requests.get(url, cookies=cookies, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract game title
        # UI Fallback: Returns "Jogo Desconhecido" (PT-BR) if not found
        game_title = soup.find("div", {"id": "appHubAppName"})
        game_title = game_title.text.strip() if game_title else "Jogo Desconhecido"

        # Extract raw text from body (Description + Reviews snippets)
        # Limit to 15k chars for token optimization
        raw_text = soup.get_text(separator=" ", strip=True)[:15000]

        return game_title, raw_text

    except Exception as e:
        print(f"Error scraping Steam: {e}")
        return None, None


async def generate_game_analysis(game_url: str):
    """
    Main Orchestrator:
    1. Extract ID & Scrape Text
    2. Fetch Price (BRL)
    3. Generate Analysis with Gemini
    """

    # 1. Extract ID
    app_id = extract_app_id(game_url)

    # 2. Scrape Text Data
    title, game_text = get_steam_text(game_url)

    # Validation: Return error HTML if scraping fails
    if not game_text or not app_id:
        return """
        <div class="p-4 mb-4 text-sm text-red-400 bg-red-900/20 rounded-lg border border-red-900 animate-fade-in">
            <span class="font-bold">Erro de Leitura!</span> Link inválido ou erro ao acessar a Steam. Verifique a URL.
        </div>
        """

    # 3. Fetch Price in BRL (More accurate than scraping)
    price_brl = get_steam_price_brl(app_id)

    # 4. Construct the Prompt
    # The prompt is in Portuguese to ensure the AI output is in PT-BR.
    prompt = f"""
    Você é um crítico de games brasileiro, especialista em Custo-Benefício e Performance Técnica no PC.
    Analise o jogo "{title}".
    
    PREÇO ATUAL NO BRASIL: {price_brl}
    
    DADOS DA STEAM (DESCRIÇÃO E REVIEWS):
    {game_text}

    Sua missão: Gere um HTML (apenas o conteúdo da div) seguindo EXATAMENTE a estrutura abaixo.
    
    Regras:
    1. Veredito: Escolha um entre "ESPERAR PROMOÇÃO" (Amarelo), "FUGIR" (Vermelho), ou "COMPRAR AGORA" (Verde).
    2. IMPORTANTE: Use o preço ({price_brl}) para decidir. Se for caro e tiver problemas técnicos, recomende esperar.
    3. Analise a performance técnica e diversão.
    4. Responda EM PORTUGUÊS DO BRASIL.
    
    MODELO HTML:
    <div class="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden shadow-2xl animate-fade-in-up">
        <div class="bg-gray-900/50 p-6 border-b border-gray-700 flex justify-between items-center">
            <h2 class="text-2xl font-bold text-white">{title}</h2>
            <span class="px-3 py-1 bg-blue-500/20 text-blue-400 text-xs font-bold uppercase tracking-wider rounded-full">
                [VEREDITO]
            </span>
        </div>
        
        <div class="p-6 space-y-4 text-left">
            <div>
                <h3 class="text-green-400 font-bold text-sm uppercase mb-1">Análise da IA</h3>
                <p class="text-gray-300 leading-relaxed">
                    [Sua análise aqui. Cite explicitamente o preço e se vale a pena.]
                </p>
            </div>
            
            <div class="mt-4 p-4 bg-gray-900 rounded-lg border border-gray-700">
                <h4 class="text-white font-bold text-xs uppercase mb-2">Resumo</h4>
                <ul class="list-disc list-inside text-gray-400 text-sm space-y-1">
                    <li>[Ponto Positivo]</li>
                    <li>[Ponto Negativo]</li>
                    <li>[Performance / Hardware]</li>
                </ul>
            </div>
        </div>
    </div>
    """

    # 5. Call Gemini API
    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Erro no Gemini 3: {e}. Tentando fallback...")
        return f"""
        <div class="p-4 text-red-400 border border-red-900 rounded-lg">
            Erro ao conectar com a IA: {e}
        </div>
        """
