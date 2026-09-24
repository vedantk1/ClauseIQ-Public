"""Canonical catalog; API metadata verified against OpenAI docs on 2026-09-24.

https://developers.openai.com/api/docs/models
Provider capacity is not an application spending budget.
"""
from typing import Any
from dataclasses import asdict, dataclass
from pydantic import BaseModel

CATALOG_VERIFIED_ON = "2026-09-24"
DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_QUERY_GATE_MODEL = "gpt-6-sol"
# Resolve retired configuration on read only. This is an explicit product
# migration, never a provider-failure fallback or a rewrite of past attribution.
_RETIRED_MODEL_SELECTIONS = dict.fromkeys(
    ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"),
    DEFAULT_MODEL,
)
_NEW_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
_BASE_PRICE_NOTE = (
    "Standard USD rates per million tokens, not a per-document estimate. "
    "Reasoning tokens are billed as output. Caching, service tiers and token "
    "usage affect the bill; check OpenAI pricing before a paid evaluation."
)
_LONG_PRICE_NOTE = (
    " Above 272,000 input tokens, the full request uses 2x input and 1.5x "
    "output rates. Cache writes cost 1.25x uncached input."
)


def resolve_retired_model_selection(model_id: str) -> str:
    """Resolve known retired saved/config choices; preserve every other value."""
    return _RETIRED_MODEL_SELECTIONS.get(model_id, model_id)


@dataclass(frozen=True)
class AIModel:
    """Represents an AI model configuration."""
    id: str
    name: str
    description: str
    context_window: int
    input_price_per_million: float
    output_price_per_million: float
    reasoning_efforts: tuple[str, ...] = _NEW_EFFORTS
    max_output_tokens: int = 128_000
    default_reasoning_effort: str = "medium"
    tokenizer_encoding: str = "o200k_base"
    pricing_verified_on: str = CATALOG_VERIFIED_ON
    pricing_note: str = _BASE_PRICE_NOTE + _LONG_PRICE_NOTE
    legacy: bool = False

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_MODEL


class AIModelResponse(BaseModel):
    """Pydantic model for API responses."""
    id: str
    name: str
    description: str
    context_window: int
    max_output_tokens: int
    reasoning_efforts: list[str]
    default_reasoning_effort: str
    input_price_per_million: float
    output_price_per_million: float
    pricing_verified_on: str
    pricing_note: str
    legacy: bool


class AIModelConfig:
    """Configuration class for AI models."""

    _models = (
        AIModel("gpt-6-luna", "GPT-6 Luna", "Lower-cost option for focused tasks and development.",
                1_050_000, 0.10, 0.50),
        AIModel("gpt-6-sol", "GPT-6 Sol", "Default balance of capability and cost for review and answers.",
                1_050_000, 2.00, 10.00),
        AIModel("gpt-6-astra", "GPT-6 Astra", "Highest-capability option with higher per-token costs.",
                1_050_000, 10.00, 50.00, reasoning_efforts=_NEW_EFFORTS[1:]),
    )

    @classmethod
    def get_available_models(cls) -> list[AIModel]:
        """Get list of all available AI models."""
        return list(cls._models)

    @classmethod
    def get_model_ids(cls) -> list[str]:
        """Get list of available model IDs."""
        return [model.id for model in cls._models]

    @classmethod
    def get_default_model(cls) -> str:
        """Get the default model ID."""
        return DEFAULT_MODEL

    @classmethod
    def get_model_by_id(cls, model_id: str) -> AIModel:
        """Get model configuration by ID."""
        for model in cls._models:
            if model.id == model_id:
                return model
        raise ValueError("Unsupported model. Choose an available model in Settings.")

    @classmethod
    def is_valid_model(cls, model_id: str) -> bool:
        """Check if a model ID is valid."""
        return model_id in cls.get_model_ids()

    @classmethod
    def get_models_for_api(cls) -> list[dict[str, Any]]:
        """Get models formatted for API response."""
        return [AIModelResponse(**asdict(model)).model_dump() for model in cls._models]


# Module-level exports for convenient access
AVAILABLE_MODELS = AIModelConfig.get_model_ids()
MODEL_DESCRIPTIONS = {model.id: model.description for model in AIModelConfig.get_available_models()}
