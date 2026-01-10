"""
Game Analysis Schema

This module defines the EXACT structure that the AI (Gemini) must return.
By using Pydantic, we ensure that:
1. The data is always validated
2. The structure is always consistent
3. We get automatic error handling if the AI returns invalid data

HOW IT WORKS:
- Pydantic is a library that validates data using Python type hints
- When we create a GameAnalysis object, Pydantic checks if all fields are correct
- If something is wrong, it raises a clear error

EXAMPLE OF VALID JSON FROM AI:
{
    "verdict": "COMPRAR AGORA",
    "verdict_color": "green",
    "analysis_text": "Este jogo é excelente...",
    "positive_points": ["Gráficos incríveis", "Gameplay fluido"],
    "negative_points": ["Preço alto"],
    "performance_notes": ["Roda bem em GTX 1060", "Requer 16GB RAM"]
}
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VerdictType(str, Enum):
    """
    Enum for the three possible verdicts.

    WHY USE ENUM?
    - Limits the AI to only these 3 options
    - Prevents typos like "COMPRA AGORA" instead of "COMPRAR AGORA"
    - Makes the code more predictable
    """

    BUY_NOW = "COMPRAR AGORA"
    WAIT_SALE = "ESPERAR PROMOÇÃO"
    AVOID = "FUGIR"


class GameAnalysis(BaseModel):
    """
    Main schema for AI analysis response.

    FIELD EXPLANATIONS:
    - verdict: The final recommendation (BUY, WAIT, or AVOID)
    - verdict_color: CSS color class (green, yellow, red)
    - analysis_text: The main analysis paragraph from AI
    - positive_points: List of good things about the game
    - negative_points: List of bad things about the game
    - performance_notes: Technical info (FPS, hardware requirements, bugs)
    """

    verdict: VerdictType = Field(
        ...,  # "..." means this field is REQUIRED
        description="The final recommendation: COMPRAR AGORA, ESPERAR PROMOÇÃO, or FUGIR",
    )

    verdict_color: str = Field(
        ..., description="Color for the verdict badge: 'green', 'yellow', or 'red'"
    )

    analysis_text: str = Field(
        ...,
        min_length=50,  # Ensures AI writes at least 50 characters
        max_length=2000,
        description="Main analysis paragraph explaining the verdict",
    )

    positive_points: list[str] = Field(
        default_factory=list,  # If AI forgets, defaults to empty list
        min_length=1,
        max_length=5,
        description="List of positive aspects (1-5 items)",
    )

    negative_points: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="List of negative aspects (0-5 items)",
    )

    performance_notes: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Technical performance notes (FPS, hardware, bugs)",
    )


class GameData(BaseModel):
    """
    Complete game data including Steam info + AI analysis.

    This combines:
    - Data from Steam API (title, price, image)
    - Data from AI analysis (verdict, points, etc.)

    WHY SEPARATE FROM GameAnalysis?
    - GameAnalysis is what the AI returns
    - GameData is the COMPLETE package we use to render the card
    """

    # Steam Data (fetched from API, not from AI)
    app_id: str
    title: str
    price: str
    image_url: str
    steam_url: str

    # AI Analysis (parsed from Gemini response)
    analysis: GameAnalysis

    # Metadata
    cached: bool = Field(
        default=False, description="Whether this result came from cache"
    )


class ErrorResponse(BaseModel):
    """
    Schema for error messages.

    Used when something goes wrong (invalid URL, API error, etc.)
    This ensures even errors have a consistent structure.
    """

    error_type: str = Field(
        ..., description="Type of error: 'invalid_url', 'steam_error', 'ai_error'"
    )

    message: str = Field(..., description="Human-readable error message in Portuguese")

    details: Optional[str] = Field(
        default=None, description="Technical details for debugging (optional)"
    )
