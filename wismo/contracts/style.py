"""PersonalizationConfig contract — style parameters for response generation."""

from pydantic import BaseModel


class PersonalizationConfig(BaseModel):
    """Canonical style configuration for personalized response generation."""

    schema_version: str = "style.v1"
    tone: str = "neutral"
    depth: str = "moderate"
    verbosity: str = "balanced"
    response_length: str = "medium"
    language_code: str = "vi"
    custom_instructions: str | None = None
