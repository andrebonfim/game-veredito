from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator


_CLS_ALIASES: dict[str, str] = {
    "g": "g", "green": "g", "verde": "g",
    "y": "y", "yellow": "y", "amarelo": "y",
    "r": "r", "red": "r", "vermelho": "r",
}


class PerformanceBar(BaseModel):
    lbl: str = Field(..., description="Short label, e.g. 'Estabilidade'")
    v: int = Field(..., description="Score 0–100")
    cls: str = Field(..., description="Color class: g=green, y=yellow, r=red")

    @field_validator("v", mode="before")
    @classmethod
    def clamp_v(cls, val: int) -> int:
        return max(0, min(100, int(val)))

    @field_validator("cls", mode="before")
    @classmethod
    def normalize_cls(cls, val: str) -> str:
        return _CLS_ALIASES.get(str(val).lower(), "y")


class VerdictType(str, Enum):
    BUY_NOW = "COMPRAR AGORA"
    WAIT_SALE = "ESPERAR PROMOÇÃO"
    AVOID = "FUGIR"


_VERDICT_TO_COLOR: dict[VerdictType, str] = {
    VerdictType.BUY_NOW: "green",
    VerdictType.WAIT_SALE: "yellow",
    VerdictType.AVOID: "red",
}


class GameAnalysis(BaseModel):
    verdict: VerdictType = Field(
        ...,
        description="The final recommendation: COMPRAR AGORA, ESPERAR PROMOÇÃO, or FUGIR",
    )

    analysis_text: str = Field(
        ...,
        min_length=100,
        max_length=2000,
        description="Main analysis paragraph explaining the verdict",
    )

    positive_points: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="List of positive aspects (required, 1-5 items)",
    )

    negative_points: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="List of negative aspects (0-5 items)",
    )

    perf_grade: Optional[str] = Field(
        default=None,
        description="Overall performance grade: 'Excelente', 'Aceitável', or 'Problemático'",
    )

    perf_notes: Optional[str] = Field(
        default=None,
        description="Descriptive text summarising performance, shown above the bars",
    )

    perf_bars: list[PerformanceBar] = Field(
        default_factory=list,
        max_length=4,
        description="Performance bars with label, score 0-100, and color class",
    )

    @computed_field
    @property
    def verdict_color(self) -> str:
        """Derived from verdict — always consistent, never supplied by the AI."""
        return _VERDICT_TO_COLOR[self.verdict]


class GameData(BaseModel):
    app_id: str
    title: str
    price: str
    discount: int = Field(default=0, description="Discount percentage, e.g. 50 for -50%")
    original_price: Optional[str] = Field(default=None, description="Full price before discount, e.g. 'R$ 199,90'")
    lowest_price: Optional[str] = Field(default=None, description="All-time low price from ITAD, e.g. 'R$ 19,99'")
    image_url: str
    steam_url: str
    review_score: Optional[int] = Field(default=None, description="Percentage of positive reviews, e.g. 78")
    analysis: GameAnalysis
    cached: bool = Field(default=False)
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("analyzed_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: object) -> datetime:
        if isinstance(v, datetime):
            return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
        return v


class StreamingAnalysisJSON(BaseModel):
    """Structured fields returned after the separator in the streaming prompt.
    analysis_text is absent — it comes from the streamed text portion."""

    verdict: VerdictType
    positive_points: list[str] = Field(..., min_length=1, max_length=5)
    negative_points: list[str] = Field(default_factory=list, max_length=5)
    perf_grade: Optional[str] = None
    perf_notes: Optional[str] = None
    perf_bars: list[PerformanceBar] = Field(default_factory=list, max_length=4)


class ErrorResponse(BaseModel):
    error_type: str = Field(
        ..., description="Type of error: 'invalid_url', 'steam_error', 'ai_error', 'rate_limit'"
    )
    message: str = Field(..., description="Human-readable error message in Portuguese")
    details: Optional[str] = Field(default=None)
