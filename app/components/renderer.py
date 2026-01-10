"""
Component Renderer Module

This module is responsible for converting structured data (GameData, ErrorResponse)
into HTML using Jinja2 templates.

WHY THIS APPROACH?
- Separation of Concerns: AI generates DATA, this module generates HTML
- Consistency: The HTML structure is ALWAYS the same, only the content changes
- Maintainability: To change the design, you only edit the templates, not the AI prompt
- Testability: We can test the renderer without calling the AI

HOW IT WORKS:
1. Receive a GameData or ErrorResponse object
2. Load the appropriate Jinja2 template
3. Pass the data to the template
4. Return the rendered HTML string
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.game import ErrorResponse, GameData

# Setup Jinja2 Environment
# This tells Jinja2 where to find the template files
TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "components"

# Create the Jinja2 environment
# autoescape=True prevents XSS attacks by escaping HTML in variables
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_analysis_card(game_data: GameData) -> str:
    """
    Renders the main analysis card component.

    PARAMETERS:
    - game_data: A GameData object containing all info about the game

    RETURNS:
    - HTML string ready to be sent to the browser

    EXAMPLE USAGE:
        game = GameData(
            app_id="1091500",
            title="Cyberpunk 2077",
            price="R$ 199,90",
            image_url="https://...",
            steam_url="https://store.steampowered.com/app/1091500",
            analysis=GameAnalysis(...)
        )
        html = render_analysis_card(game)
    """
    template = jinja_env.get_template("analysis_card.html")

    # Convert Pydantic model to dict for Jinja2
    # model_dump() is the Pydantic v2 way to convert to dict
    return template.render(game=game_data.model_dump())


def render_error(error: ErrorResponse) -> str:
    """
    Renders an error alert component.

    PARAMETERS:
    - error: An ErrorResponse object with error details

    RETURNS:
    - HTML string for the error alert

    ERROR TYPES AND THEIR COLORS:
    - invalid_url: Red (user mistake)
    - steam_error: Yellow (external service issue)
    - ai_error: Yellow (temporary AI issue)
    """
    template = jinja_env.get_template("error_alert.html")
    return template.render(error=error.model_dump())


def render_error_simple(error_type: str, message: str, details: str = None) -> str:
    """
    Convenience function to render errors without creating an ErrorResponse object.

    This is useful when you want to quickly render an error without all the ceremony
    of creating a Pydantic object first.

    EXAMPLE:
        html = render_error_simple(
            error_type="invalid_url",
            message="Link inválido! Verifique a URL."
        )
    """
    error = ErrorResponse(error_type=error_type, message=message, details=details)
    return render_error(error)


# Color mapping for verdicts
# This is used by the template to apply the correct CSS classes
VERDICT_COLORS = {
    "green": {
        "bg": "bg-green-500/20",
        "text": "text-green-400",
        "border": "border-green-500/30",
    },
    "yellow": {
        "bg": "bg-yellow-500/20",
        "text": "text-yellow-400",
        "border": "border-yellow-500/30",
    },
    "red": {
        "bg": "bg-red-500/20",
        "text": "text-red-400",
        "border": "border-red-500/30",
    },
}


def get_verdict_colors(color: str) -> dict:
    """
    Returns the CSS classes for a given verdict color.

    Falls back to yellow if an unknown color is provided.
    """
    return VERDICT_COLORS.get(color, VERDICT_COLORS["yellow"])
