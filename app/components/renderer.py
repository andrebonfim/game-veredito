from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.game import ErrorResponse, GameData

# Root templates directory — same base as FastAPI's Jinja2Templates in routers/home.py
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_analysis_card(game_data: GameData) -> str:
    template = jinja_env.get_template("components/analysis_card.html")
    return template.render(game=game_data.model_dump(mode="json"))


def _render_error(error: ErrorResponse) -> str:
    template = jinja_env.get_template("components/error_alert.html")
    return template.render(error=error.model_dump(mode="json"))


def render_card_skeleton(partial: dict, stream_id: str) -> str:
    template = jinja_env.get_template("components/analysis_card_skeleton.html")
    return template.render(game=partial, stream_id=stream_id)


def render_verdict_block(game_data: GameData, app_id: str, stream_id: str = "") -> str:
    template = jinja_env.get_template("components/analysis_verdict_block.html")
    return template.render(game=game_data.model_dump(mode="json"), app_id=app_id, stream_id=stream_id)


def render_error_simple(error_type: str, message: str, details: str = None) -> str:
    error = ErrorResponse(error_type=error_type, message=message, details=details)
    return _render_error(error)
