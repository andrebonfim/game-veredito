import asyncio
import html as html_mod
import json
import logging
import re
from typing import AsyncGenerator, Optional
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from cachetools import TTLCache
from google import genai
from pydantic import ValidationError

from app.components.renderer import render_analysis_card, render_card_skeleton, render_error_simple, render_verdict_block
from app.core.config import settings
from app.schemas.game import GameAnalysis, GameData, StreamingAnalysisJSON

log = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GEMINI_API_KEY)

# In-memory cache keyed by Steam App ID.
# NOTE: per-process — each uvicorn worker keeps its own cache. With multiple
# workers (--workers N) the same game may be fetched more than once across
# processes. Acceptable for the current single-worker deployment.
game_cache: TTLCache[str, GameData] = TTLCache(maxsize=100, ttl=86400)

# Maps Steam app_id → ITAD UUID. UUIDs are permanent; no TTL needed.
_itad_id_cache: dict[str, str] = {}

# Maps stream_id (UUID hex) → partial game data dict for the SSE stream phase.
# Entry is popped when the SSE generator starts — prevents replay on reconnect.
_pending_streams: dict[str, dict] = {}


def get_history() -> list:
    """Returns all persisted analyses sorted newest-first."""
    from app.core.database import load_all_analyses
    return load_all_analyses()


def extract_app_id(url: str) -> Optional[str]:
    match = re.search(r"/app/(\d+)", url)
    return match.group(1) if match else None


def get_steam_api_data(app_id: str) -> dict:
    """Returns {"price": str, "image": str, "discount": int}."""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&l=brazilian"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data or not data.get(app_id) or not data[app_id]["success"]:
            return {"price": "Preço indisponível", "image": "", "discount": 0}

        game_data = data[app_id]["data"]
        image_url = game_data.get("header_image", "")

        price_text = "Não listado"
        discount = 0
        original_price = None
        if game_data.get("is_free"):
            price_text = "Gratuito (Free to Play)"
        elif game_data.get("price_overview"):
            price_overview = game_data["price_overview"]
            price_text = price_overview.get("final_formatted", "Não listado")
            discount = price_overview.get("discount_percent", 0)
            if discount > 0:
                original_price = price_overview.get("initial_formatted")

        return {"price": price_text, "image": image_url, "discount": discount, "original_price": original_price}

    except Exception as e:
        log.warning("Steam API request failed for app_id=%s: %s", app_id, e)
        return {"price": "Erro", "image": "", "discount": 0}


def _fmt_brl(amount: float) -> str:
    """Formats a float as a BRL price string, e.g. 1999.9 → 'R$ 1.999,90'."""
    formatted = f"{amount:,.2f}"  # "1,999.90" (US locale)
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _parse_brl(price_str: str) -> Optional[float]:
    """Parses 'R$ 1.999,90' → 1999.90. Returns None if unparseable."""
    try:
        cleaned = price_str.replace("R$", "").strip()
        cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def get_itad_lowest_price(app_id: str) -> Optional[str]:
    """Fetches the all-time lowest price for a game from IsThereAnyDeal.
    Step 1: POST /lookup/id/shop/61/v1 resolves the Steam appid to an ITAD UUID.
    Step 2: POST /games/overview/v2 returns historyLow for that UUID.
    Returns a formatted BRL string or None if unavailable / key not set."""
    if not settings.ITAD_API_KEY:
        return None
    try:
        game_id: Optional[str] = _itad_id_cache.get(app_id)
        if not game_id:
            resp = requests.post(
                "https://api.isthereanydeal.com/lookup/id/shop/61/v1",
                params={"key": settings.ITAD_API_KEY},
                json=[f"app/{app_id}"],
                timeout=2,
            )
            resp.raise_for_status()
            game_id = resp.json().get(f"app/{app_id}")
            if not game_id:
                return None
            _itad_id_cache[app_id] = game_id
        else:
            log.debug("ITAD UUID cache hit for app_id=%s", app_id)

        resp2 = requests.post(
            "https://api.isthereanydeal.com/games/overview/v2",
            params={"key": settings.ITAD_API_KEY, "country": "BR"},
            json=[game_id],
            timeout=2,
        )
        resp2.raise_for_status()
        data = resp2.json()

        prices = data.get("prices") if isinstance(data, dict) else None
        if not prices:
            return None
        amount: float = prices[0]["lowest"]["price"]["amount"]
        return _fmt_brl(amount)

    except Exception as e:
        log.warning("ITAD request failed for app_id=%s: %s", app_id, e)
        return None


def get_steam_reviews(app_id: str) -> tuple[str, Optional[int]]:
    try:
        url = (
            f"https://store.steampowered.com/appreviews/{app_id}"
            "?json=1&filter=summary&language=all&num_per_page=10&purchase_type=all"
        )
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        review_score: Optional[int] = None
        summary = data.get("query_summary", {})
        total = summary.get("total_reviews", 0)
        if total > 0:
            review_score = round(summary.get("total_positive", 0) / total * 100)

        if not data or "reviews" not in data:
            return "Não foi possível ler os reviews dos usuários.", review_score

        reviews_list = []
        for review in data["reviews"]:
            text = review.get("review", "").replace("\n", " ")[:500]
            votes = review.get("votes_up", 0)
            reviews_list.append(f"- ({votes} votos positivos): {text}")

        return "\n".join(reviews_list), review_score

    except Exception as e:
        log.warning("Steam reviews request failed for app_id=%s: %s", app_id, e)
        return "Erro ao buscar reviews.", None


def get_steam_store_text(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (title, store_text, page_fallback_price).
    page_fallback_price is the minimum price found in .game_purchase_price elements,
    formatted as a BRL string — used when the Steam API returns no price_overview."""
    try:
        cookies = {"birthtime": "568022401", "lastagecheckage": "1-January-1988"}
        response = requests.get(url, cookies=cookies, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Scrape page prices before decomposing tags.
        fallback_price: Optional[str] = None
        price_els = soup.select(".game_purchase_price")
        if price_els:
            amounts = [_parse_brl(el.get_text(strip=True)) for el in price_els]
            valid = [a for a in amounts if a is not None]
            if valid:
                fallback_price = _fmt_brl(min(valid))

        # Remove script/style content before extracting text — avoids injecting
        # JS/CSS into the AI prompt and wastes tokens.
        for tag in soup(["script", "style"]):
            tag.decompose()

        game_title_el = soup.find("div", {"id": "appHubAppName"})
        game_title = game_title_el.text.strip() if game_title_el else "Jogo Desconhecido"

        description = soup.find("div", {"id": "game_area_description"})
        if description:
            raw_text = description.get_text(separator=" ", strip=True)[:10000]
        else:
            raw_text = soup.get_text(separator=" ", strip=True)[:10000]

        return game_title, raw_text, fallback_price

    except Exception as e:
        log.warning("Steam store page scrape failed for url=%s: %s", url, e)
        return None, None, None


def parse_ai_json_response(response_text: str) -> Optional[GameAnalysis]:
    try:
        text = response_text.strip()

        # Extract the first {...} block from anywhere in the response.
        # Handles markdown fences (```json ... ```), preamble text, etc.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        data = json.loads(text)
        return GameAnalysis(**data)

    except json.JSONDecodeError as e:
        log.error("AI JSON parse error: %s | raw=%.300s", e, response_text)
        return None
    except ValidationError as e:
        log.error("AI response validation error: %s", e)
        return None


def _build_price_context(price_brl: str, lowest_price: Optional[str], review_score: Optional[int] = None) -> str:
    ctx = f"PREÇO ATUAL: {price_brl}"
    if lowest_price:
        current = _parse_brl(price_brl)
        historic = _parse_brl(lowest_price)
        if current is not None and historic is not None and current > historic:
            diff = _fmt_brl(current - historic)
            ctx += f"\nMENOR PREÇO HISTÓRICO: {lowest_price} (você pagaria {diff} a mais agora)"
        else:
            ctx += f"\nMENOR PREÇO HISTÓRICO: {lowest_price}"
    if review_score is not None:
        ctx += f"\nREVIEWS POSITIVAS NA STEAM: {review_score}%"
    return ctx


_STREAM_SEPARATOR = "---JSON---"
_SEP_LEN = len(_STREAM_SEPARATOR)


def build_streaming_prompt(
    title: str,
    price_brl: str,
    store_text: str,
    user_reviews: str,
    lowest_price: Optional[str] = None,
    review_score: Optional[int] = None,
) -> str:
    price_context = _build_price_context(price_brl, lowest_price, review_score)

    return f"""
Você é aquele amigo gamer que todo mundo tem — jogou de tudo, sabe o que vale e não tem papas na língua.
Sua missão: dar um veredito honesto sobre "{title}" pra galera que tá na dúvida se compra ou não.

{price_context}

O QUE A DESENVOLVEDORA PROMETE:
{store_text}

O QUE OS JOGADORES ESTÃO FALANDO (reviews reais — presta atenção nos bugs e na performance):
{user_reviews}

INSTRUÇÕES:
- Fala como gamer, não como jornalista. Sem enrolação, sem papo corporativo.
- Vai direto ao ponto: vale o preço ou não? Por quê?
- Menciona o preço ({price_brl}) e se tá justo pelo que o jogo entrega.
- Se tiver bug feio ou problema de performance nos reviews, fala sem dó.
- Usa expressões naturais do dia a dia gamer brasileiro.

FORMATO DE RESPOSTA — DUAS PARTES SEPARADAS EXATAMENTE PELO MARCADOR {_STREAM_SEPARATOR}:

PARTE 1 — SUA ANÁLISE (texto puro, mínimo 100 palavras, sem markdown, sem listas):

---JSON---
{{
    "verdict": "COMPRAR AGORA" | "ESPERAR PROMOÇÃO" | "FUGIR",
    "positive_points": ["ponto positivo 1", "ponto positivo 2"],
    "negative_points": ["ponto negativo 1"],
    "perf_bars": [
        {{"lbl": "Estabilidade", "v": 76, "cls": "y"}},
        {{"lbl": "Performance", "v": 85, "cls": "g"}}
    ]
}}

REGRAS:
- Escreva EXATAMENTE o marcador {_STREAM_SEPARATOR} entre as duas partes (sem espaços antes ou depois)
- verdict: EXATAMENTE um dos três valores acima
- positive_points: 1 a 5 itens (obrigatório)
- negative_points: 0 a 5 itens
- perf_bars: 1 a 4 itens (obrigatório), cls: "g" (>=70), "y" (40-69), "r" (<40)
- Nada antes da análise, nada depois do JSON
"""


def _parse_streaming_response(json_text: str, analysis_text: str) -> Optional[GameAnalysis]:
    try:
        text = json_text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
        data = json.loads(text)
        structured = StreamingAnalysisJSON(**data)
        return GameAnalysis(
            verdict=structured.verdict,
            analysis_text=analysis_text.strip() or "Análise gerada.",
            positive_points=structured.positive_points,
            negative_points=structured.negative_points,
            perf_bars=structured.perf_bars,
        )
    except Exception as e:
        log.error("Streaming JSON parse error: %s | raw=%.300s", e, json_text)
        return None


async def prepare_analysis_stream(game_url: str) -> tuple[str, str] | str:
    """Phase 1: gather Steam/ITAD data and return (stream_id, skeleton_html).
    Returns an error HTML string on failure."""
    app_id = extract_app_id(game_url)
    if not app_id:
        return render_error_simple(error_type="invalid_url", message="Link inválido.")

    title, store_text, page_price = await asyncio.to_thread(get_steam_store_text, game_url)
    if not store_text:
        return render_error_simple(
            error_type="steam_error",
            message="Erro ao acessar a Steam!",
            details="Não consegui ler a página do jogo. Tente novamente.",
        )

    (user_reviews, review_score), api_data, lowest_price = await asyncio.gather(
        asyncio.to_thread(get_steam_reviews, app_id),
        asyncio.to_thread(get_steam_api_data, app_id),
        asyncio.to_thread(get_itad_lowest_price, app_id),
    )
    price_brl: str = api_data["price"]
    if price_brl == "Não listado" and page_price:
        price_brl = f"a partir de {page_price}"
    image_url: str = api_data["image"]
    discount: int = api_data["discount"]
    original_price: Optional[str] = api_data["original_price"]

    prompt = build_streaming_prompt(title, price_brl, store_text, user_reviews, lowest_price, review_score)
    stream_id = uuid4().hex

    _pending_streams[stream_id] = {
        "app_id": app_id,
        "title": title,
        "steam_url": game_url,
        "price_brl": price_brl,
        "image_url": image_url,
        "discount": discount,
        "original_price": original_price,
        "lowest_price": lowest_price,
        "review_score": review_score,
        "prompt": prompt,
    }

    partial = {
        "app_id": app_id,
        "title": title,
        "price": price_brl,
        "discount": discount,
        "original_price": original_price,
        "lowest_price": lowest_price,
        "image_url": image_url,
        "steam_url": game_url,
        "review_score": review_score,
    }
    skeleton_html = render_card_skeleton(partial, stream_id)
    log.info("Stream prepared for app_id=%s stream_id=%s", app_id, stream_id)
    return stream_id, skeleton_html


async def stream_game_analysis(stream_id: str) -> AsyncGenerator[str, None]:
    """Phase 2 SSE generator. Yields SSE event strings."""
    data = _pending_streams.pop(stream_id, None)
    if not data:
        yield "event: error\ndata: Stream expirado ou não encontrado.\n\n"
        return

    analysis_parts: list[str] = []
    state = {"json_raw": ""}

    async def _run_stream(model: str) -> AsyncGenerator[str, None]:
        """Inner generator: streams one model, yields SSE chunk events, populates state."""
        pre_buf = ""
        sep_found = False
        jbuf = ""

        try:
            async for chunk in await client.aio.models.generate_content_stream(
                model=model, contents=data["prompt"]
            ):
                text = chunk.text or ""
                if sep_found:
                    jbuf += text
                else:
                    pre_buf += text
                    if _STREAM_SEPARATOR in pre_buf:
                        idx = pre_buf.index(_STREAM_SEPARATOR)
                        remaining = pre_buf[:idx]
                        jbuf = pre_buf[idx + _SEP_LEN:]
                        sep_found = True
                        if remaining:
                            analysis_parts.append(remaining)
                            yield f"event: chunk\ndata: {html_mod.escape(remaining)}\n\n"
                    else:
                        safe_end = max(0, len(pre_buf) - (_SEP_LEN - 1))
                        if safe_end > 0:
                            safe = pre_buf[:safe_end]
                            pre_buf = pre_buf[safe_end:]
                            analysis_parts.append(safe)
                            yield f"event: chunk\ndata: {html_mod.escape(safe)}\n\n"
        finally:
            if not sep_found and pre_buf:
                analysis_parts.append(pre_buf)
                yield f"event: chunk\ndata: {html_mod.escape(pre_buf)}\n\n"
            state["json_raw"] = jbuf

    # Try primary model; fall back on retryable errors before any text is sent
    try:
        async for event in _run_stream(_PRIMARY_MODEL):
            yield event
    except Exception as e:
        if _is_retryable_gemini_error(e) and not analysis_parts:
            log.warning("Primary stream failed before first chunk, retrying with %s: %s", _FALLBACK_MODEL, e)
            analysis_parts.clear()
            state["json_raw"] = ""
            try:
                async for event in _run_stream(_FALLBACK_MODEL):
                    yield event
            except Exception as e2:
                log.error("Fallback stream also failed: %s", e2)
                yield "event: error\ndata: Erro ao gerar análise.\n\n"
                return
        else:
            log.error("Stream error (non-retryable or mid-stream): %s", e)
            yield "event: error\ndata: Erro ao gerar análise. Tente novamente.\n\n"
            return

    analysis_text = "".join(analysis_parts).strip()
    json_raw = state["json_raw"]

    # Graceful fallback: if separator was never emitted, treat full response as legacy JSON
    if not json_raw and analysis_text:
        log.warning("Separator not found in stream for app_id=%s; attempting full-text JSON parse", data["app_id"])
        analysis = parse_ai_json_response(analysis_text)
    else:
        analysis = _parse_streaming_response(json_raw, analysis_text)

    if not analysis:
        yield "event: error\ndata: Erro ao processar resposta da IA. Tente novamente.\n\n"
        return

    game_data = GameData(
        app_id=data["app_id"],
        title=data["title"],
        price=data["price_brl"],
        discount=data["discount"],
        original_price=data["original_price"],
        lowest_price=data["lowest_price"],
        image_url=data["image_url"],
        steam_url=data["steam_url"],
        review_score=data["review_score"],
        analysis=analysis,
    )
    game_cache[data["app_id"]] = game_data
    await asyncio.to_thread(_persist_analysis, game_data)

    verdict_html = render_verdict_block(game_data, data["app_id"]).replace("\n", " ")
    yield f"event: complete\ndata: {verdict_html}\n\n"
    log.info("Stream complete for app_id=%s", data["app_id"])


def _persist_analysis(game_data) -> None:
    from app.core.database import save_analysis
    try:
        save_analysis(game_data)
    except Exception as e:
        log.warning("Failed to persist app_id=%s to DB: %s", game_data.app_id, e)


_PRIMARY_MODEL = "gemini-3.1-flash-lite-preview"
_FALLBACK_MODEL = "gemini-2.5-flash"


def _is_retryable_gemini_error(e: Exception) -> bool:
    msg = str(e)
    return any(code in msg for code in ("503", "429", "404", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "NOT_FOUND"))


