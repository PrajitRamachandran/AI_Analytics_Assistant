"""
Module 4: Provider-agnostic LLM client contract.

The analytics planner depends only on ``PlanLLMClient``. Ollama is the
first implementation; a Mistral (or any other) client can be added by
implementing the same protocol and registering a factory, without
touching the prompt builder, validator or planner.

Provider selection at runtime uses the ``LLM_PROVIDER`` environment
variable (default: ``ollama``).
"""

from __future__ import annotations

import os
from typing import Callable, Optional, Protocol, runtime_checkable

from dotenv import load_dotenv

from app.schemas.analytics_plan import WorkbookAnalyticsPlan


# ============================================================
# ERRORS (PROVIDER-NEUTRAL)
# ============================================================

class LLMClientError(Exception):
    """Base exception for LLM provider failures."""


class LLMConnectionError(LLMClientError):
    """Raised when the provider cannot be reached."""


class LLMTimeoutError(LLMClientError):
    """Raised when the provider takes too long to respond."""


class LLMPromptTooLargeError(LLMClientError):
    """Raised when the prompt cannot fit the model's context window."""


class LLMResponseError(LLMClientError):
    """
    Raised when the provider returns unusable output.

    ``raw_output`` carries the model's text (when available) so the
    planner can show the model its own mistake and ask for a correction.
    """

    def __init__(
        self,
        message: str,
        raw_output: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class LLMOutputTruncatedError(LLMResponseError):
    """Raised when generation stopped at the output-token limit."""


# ============================================================
# CLIENT PROTOCOL
# ============================================================

@runtime_checkable
class PlanLLMClient(Protocol):
    """
    Contract every LLM provider implementation must satisfy.

    ``generate_plan`` receives chat messages, requests output constrained
    to the ``WorkbookAnalyticsPlan`` JSON schema, and returns a
    schema-valid plan. It must raise ``LLMClientError`` subclasses (never
    provider-specific exceptions) on failure. Dataset-level validation is
    performed afterwards by the planner, never by the client.
    """

    provider: str
    model: str

    def generate_plan(
        self,
        messages: list[dict[str, str]],
    ) -> WorkbookAnalyticsPlan:
        ...

    def check_connection(self) -> bool:
        ...


# ============================================================
# SHARED MESSAGE VALIDATION
# ============================================================

def validate_chat_messages(messages: list[dict[str, str]]) -> None:
    """Validate chat-message structure shared by all providers."""

    if not messages:
        raise ValueError("At least one chat message is required.")

    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"system", "user", "assistant"}
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            raise ValueError("Invalid chat message structure.")


# ============================================================
# PROVIDER REGISTRY
# ============================================================

_PROVIDER_FACTORIES: dict[str, Callable[[], PlanLLMClient]] = {}


def register_llm_provider(
    name: str,
    factory: Callable[[], PlanLLMClient],
) -> None:
    """Register a factory that builds a client for ``name``."""

    if not name or not name.strip():
        raise ValueError("Provider name cannot be empty.")

    _PROVIDER_FACTORIES[name.strip().lower()] = factory


def _ollama_factory(model: str | None = None) -> PlanLLMClient:
    # Import lazily to avoid loading provider implementations unnecessarily.
    from app.modules.analytics_planner.ollama_client import create_ollama_client

    return create_ollama_client(model=model)


def _groq_factory(model: str | None = None) -> PlanLLMClient:
    # Import lazily because GroqClient imports the shared error definitions above.
    from app.modules.analytics_planner.groq_client import create_groq_client

    return create_groq_client(model=model)


register_llm_provider("ollama", _ollama_factory)
register_llm_provider("groq", _groq_factory)


def create_llm_client(provider: Optional[str] = None, model: Optional[str] = None) -> PlanLLMClient:
    """
    Create the configured LLM client.

    Args:
        provider: Provider name. Defaults to the ``LLM_PROVIDER``
            environment variable, then ``ollama``.

    Raises:
        ValueError: If the provider is unknown.
    """

    # Load .env at client-creation time so provider selection and credentials
    # are available even when the application entry point did not load it.
    load_dotenv(override=False)

    configured_provider = provider if provider is not None else os.getenv("LLM_PROVIDER")
    name = (configured_provider or "ollama").strip().lower()

    factory = _PROVIDER_FACTORIES.get(name)

    if factory is None:
        available = ", ".join(sorted(_PROVIDER_FACTORIES)) or "none"

        raise ValueError(
            f"Unknown LLM provider '{name}'. "
            f"Registered providers: {available}."
        )

    return factory() if model is None else factory(model)
