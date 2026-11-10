"""Ollama client for generating structured analytics plans."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.modules.analytics_planner.errors import PlanSchemaValidationError
from app.schemas.analytics_plan import WorkbookAnalyticsPlan

logger = logging.getLogger(__name__)
CHARS_PER_ESTIMATED_TOKEN = 3.2


class OllamaClientError(Exception):
    """Base exception for Ollama client failures."""


class OllamaConnectionError(OllamaClientError):
    """Raised when Ollama cannot be reached."""


class OllamaTimeoutError(OllamaClientError):
    """Raised when Ollama takes too long to respond."""


class OllamaResponseError(OllamaClientError):
    """Raised when Ollama returns an invalid response."""


class OllamaSchemaValidationError(OllamaResponseError, PlanSchemaValidationError):
    """Ollama returned JSON that failed the shared analytics-plan schema."""


class OllamaClient:
    """Communicate with a locally running Ollama model."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3.5:4b",
        timeout_seconds: float = 600.0,
        temperature: float = 0.1,
        context_length: int = 12288,
        max_output_tokens: int = 1024,
        disable_thinking: bool = True,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Ollama base URL cannot be empty.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Ollama model name cannot be empty.")
        try:
            timeout_seconds = float(timeout_seconds)
            temperature = float(temperature)
            context_length = int(context_length)
            max_output_tokens = int(max_output_tokens)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Ollama timeout, temperature, and token limits must be numeric.") from exc

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Timeout must be a finite number greater than zero.")
        if context_length <= 0 or max_output_tokens <= 0:
            raise ValueError("Token limits must be greater than zero.")
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("Temperature must be a finite value between 0 and 2.")

        parsed_url = httpx.URL(base_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("Ollama base URL must be a valid HTTP(S) URL.")

        self.base_url = str(parsed_url).rstrip("/")
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens
        self.disable_thinking = bool(disable_thinking)
        self._output_schema = WorkbookAnalyticsPlan.model_json_schema()

    def _http_timeout(self) -> httpx.Timeout:
        """Use a short connection timeout and a longer inference read timeout."""
        return httpx.Timeout(
            connect=min(10.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=min(30.0, self.timeout_seconds),
            pool=min(10.0, self.timeout_seconds),
        )

    def generate_plan(
        self,
        messages: list[dict[str, str]],
    ) -> WorkbookAnalyticsPlan:
        """Send messages to Ollama and return a schema-validated plan."""
        if not isinstance(messages, list) or not messages:
            raise ValueError("At least one chat message is required.")

        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant"}
                or not isinstance(message.get("content"), str)
                or not message["content"].strip()
            ):
                raise ValueError("Invalid chat message structure.")

        effective_output_tokens = min(
            self.max_output_tokens, max(256, self.context_length // 4)
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": self._output_schema,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_length,
                "num_predict": effective_output_tokens,
                "seed": 42,
            },
            # Qwen reasoning is disabled by default for this constrained
            # extraction/planning task; all arithmetic remains deterministic.
            "think": not self.disable_thinking,
        }

        message_characters = sum(len(message["content"]) for message in messages)
        schema_characters = len(json.dumps(
            self._output_schema, ensure_ascii=False, separators=(",", ":")
        ))
        estimated_prompt_tokens = math.ceil(
            (message_characters + schema_characters) / CHARS_PER_ESTIMATED_TOKEN
        )
        safety_margin_tokens = max(128, math.ceil(self.context_length * 0.05))
        available_prompt_tokens = (
            self.context_length - effective_output_tokens - safety_margin_tokens
        )
        if estimated_prompt_tokens > available_prompt_tokens:
            raise OllamaResponseError(
                "The analytics prompt is too large for the configured Ollama context: "
                f"estimated input (messages + JSON schema) is about "
                f"{estimated_prompt_tokens} tokens; available input budget is "
                f"{available_prompt_tokens} tokens after reserving "
                f"{effective_output_tokens} output tokens and "
                f"{safety_margin_tokens} safety tokens. Reduce the prepared "
                "workbook profile; increasing context also increases memory use."
            )

        logger.info(
            "Starting Ollama analytics inference: model=%s message_count=%d "
            "message_characters=%d schema_characters=%d estimated_prompt_tokens=%d "
            "context_length=%d output_tokens=%d safety_margin_tokens=%d timeout_seconds=%.1f",
            self.model,
            len(messages),
            message_characters,
            schema_characters,
            estimated_prompt_tokens,
            self.context_length,
            effective_output_tokens,
            safety_margin_tokens,
            self.timeout_seconds,
        )
        started_at = time.perf_counter()
        try:
            with httpx.Client(
                timeout=self._http_timeout(),
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - started_at
            logger.error(
                "Ollama inference timed out: model=%s elapsed_seconds=%.1f timeout_seconds=%.1f",
                self.model,
                elapsed,
                self.timeout_seconds,
            )
            raise OllamaTimeoutError(
                f"Ollama model '{self.model}' did not finish within "
                f"{self.timeout_seconds:.0f} seconds. Check Ollama resource usage, "
                "model loading, context size, and generation speed."
            ) from exc
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Start Ollama and verify that the configured host and port are correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:1000]
            raise OllamaResponseError(
                f"Ollama returned HTTP {exc.response.status_code}: {error_body}"
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaConnectionError(f"Ollama request failed: {exc}") from exc

        elapsed = time.perf_counter() - started_at
        try:
            response_data = response.json()
        except ValueError as exc:
            raise OllamaResponseError(
                "Ollama returned a response that was not valid JSON."
            ) from exc

        if not isinstance(response_data, dict):
            raise OllamaResponseError("Ollama response must be a JSON object.")
        if response_data.get("error"):
            raise OllamaResponseError(
                f"Ollama reported an inference error: {str(response_data['error'])[:500]}"
            )
        if response_data.get("done") is False or response_data.get("done_reason") == "length":
            raise OllamaResponseError(
                "Ollama stopped before completing the response because the output-token "
                f"limit ({effective_output_tokens}) was reached. Increase OLLAMA_MAX_OUTPUT_TOKENS "
                "or simplify the requested plan."
            )

        message_data = response_data.get("message")
        if not isinstance(message_data, dict):
            raise OllamaResponseError("Ollama response does not contain a valid message.")

        content = message_data.get("content")
        if not isinstance(content, str) or not content.strip():
            thinking = message_data.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                raise OllamaResponseError(
                    "Ollama returned reasoning but no answer content. Ensure thinking is disabled."
                )
            raise OllamaResponseError("Ollama returned empty response content.")

        try:
            parsed_json = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise OllamaResponseError(
                "Ollama did not return valid JSON content."
            ) from exc

        try:
            plan = WorkbookAnalyticsPlan.model_validate(parsed_json)
        except ValidationError as exc:
            error_details = exc.errors(
                include_input=False,
                include_context=False,
                include_url=False,
            )
            raise OllamaSchemaValidationError(
                "Ollama returned JSON that does not match the analytics plan schema.",
                generated_output=content,
                validation_errors=error_details,
            ) from exc

        logger.info(
            "Ollama analytics plan generated: model=%s elapsed_seconds=%.1f "
            "prompt_tokens=%s output_tokens=%s done_reason=%s",
            self.model,
            elapsed,
            response_data.get("prompt_eval_count", "unknown"),
            response_data.get("eval_count", "unknown"),
            response_data.get("done_reason", "unknown"),
        )
        return plan

    def check_connection(self) -> bool:
        """Return whether the Ollama tags endpoint is reachable."""
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0), trust_env=False) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value (true/false).")


def create_ollama_client() -> OllamaClient:
    """Create the V1 Ollama client, with optional environment overrides."""
    try:
        timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))
        temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
        context_length = int(os.getenv("OLLAMA_CONTEXT_LENGTH", "12288"))
        max_output_tokens = int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "1024"))
    except ValueError as exc:
        raise ValueError("One or more OLLAMA numeric settings are invalid.") from exc

    return OllamaClient(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        context_length=context_length,
        max_output_tokens=max_output_tokens,
        disable_thinking=_env_bool("OLLAMA_DISABLE_THINKING", True),
    )
