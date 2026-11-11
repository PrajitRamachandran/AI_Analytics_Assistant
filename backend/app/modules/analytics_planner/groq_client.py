"""Groq client for generating structured analytics plans."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.modules.analytics_planner.llm_client import (
    LLMConnectionError,
    LLMOutputTruncatedError,
    LLMPromptTooLargeError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.modules.analytics_planner.errors import PlanSchemaValidationError
from app.schemas.analytics_plan import WorkbookAnalyticsPlan

logger = logging.getLogger(__name__)

CHARS_PER_ESTIMATED_TOKEN = 3.2
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
DEFAULT_CONTEXT_LENGTH = 131072


class GroqClient:
    """Generate schema-validated analytics plans using Groq hosted inference."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GROQ_MODEL,
        base_url: str = DEFAULT_GROQ_BASE_URL,
        timeout_seconds: float = 120.0,
        temperature: float = 0.1,
        context_length: int = DEFAULT_CONTEXT_LENGTH,
        max_output_tokens: int = 8192,
        reasoning_effort: str = "none",
        strict_json_schema: bool = False,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Groq API key cannot be empty.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Groq model name cannot be empty.")

        try:
            timeout_seconds = float(timeout_seconds)
            temperature = float(temperature)
            context_length = int(context_length)
            max_output_tokens = int(max_output_tokens)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "Groq timeout, temperature, and token limits must be numeric."
            ) from exc

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Timeout must be a finite number greater than zero.")
        if context_length <= 0 or max_output_tokens <= 0:
            raise ValueError("Token limits must be greater than zero.")
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("Temperature must be a finite value between 0 and 2.")

        normalized_effort = reasoning_effort.strip().lower()
        if normalized_effort not in {"none", "default", "low", "medium", "high"}:
            raise ValueError(
                "GROQ_REASONING_EFFORT must be one of: none, default, low, medium, high."
            )

        parsed_url = httpx.URL(base_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("Groq base URL must be a valid HTTP(S) URL.")

        self.provider = "groq"
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = str(parsed_url).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = normalized_effort
        self.strict_json_schema = bool(strict_json_schema)
        self._output_schema = WorkbookAnalyticsPlan.model_json_schema()

    def _http_timeout(self) -> httpx.Timeout:
        """Use a short connection timeout and a longer inference read timeout."""
        return httpx.Timeout(
            connect=min(10.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=min(30.0, self.timeout_seconds),
            pool=min(10.0, self.timeout_seconds),
        )

    @staticmethod
    def _validate_messages(messages: list[dict[str, str]]) -> None:
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

    def _estimate_prompt_tokens(self, messages: list[dict[str, str]]) -> tuple[int, int, int]:
        message_characters = sum(len(message["content"]) for message in messages)
        schema_characters = len(
            json.dumps(self._output_schema, ensure_ascii=False, separators=(",", ":"))
        )
        estimated_tokens = math.ceil(
            (message_characters + schema_characters) / CHARS_PER_ESTIMATED_TOKEN
        )
        effective_output_tokens = min(
            self.max_output_tokens,
            max(256, self.context_length // 4),
        )
        safety_margin_tokens = max(256, math.ceil(self.context_length * 0.02))
        available_prompt_tokens = (
            self.context_length - effective_output_tokens - safety_margin_tokens
        )

        if estimated_tokens > available_prompt_tokens:
            raise LLMPromptTooLargeError(
                "The analytics prompt is too large for the configured Groq context: "
                f"estimated input (messages + JSON schema) is about {estimated_tokens} "
                f"tokens; available input budget is {available_prompt_tokens} tokens "
                f"after reserving {effective_output_tokens} output tokens and "
                f"{safety_margin_tokens} safety tokens. Reduce the prepared workbook profile."
            )

        return estimated_tokens, effective_output_tokens, safety_margin_tokens

    def generate_plan(
        self,
        messages: list[dict[str, str]],
    ) -> WorkbookAnalyticsPlan:
        """Send messages to Groq and return a Pydantic-validated analytics plan."""
        self._validate_messages(messages)

        (
            estimated_prompt_tokens,
            effective_output_tokens,
            safety_margin_tokens,
        ) = self._estimate_prompt_tokens(messages)

        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "workbook_analytics_plan",
                "schema": self._output_schema,
                "strict": self.strict_json_schema,
            },
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": effective_output_tokens,
            "response_format": response_format,
            "reasoning_effort": self.reasoning_effort,
            "stream": False,
        }

        logger.info(
            "Starting Groq analytics inference: model=%s message_count=%d "
            "estimated_prompt_tokens=%d context_length=%d output_tokens=%d "
            "safety_margin_tokens=%d timeout_seconds=%.1f reasoning_effort=%s "
            "strict_json_schema=%s",
            self.model,
            len(messages),
            estimated_prompt_tokens,
            self.context_length,
            effective_output_tokens,
            safety_margin_tokens,
            self.timeout_seconds,
            self.reasoning_effort,
            self.strict_json_schema,
        )

        started_at = time.perf_counter()
        try:
            with httpx.Client(
                timeout=self._http_timeout(),
                trust_env=False,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                )
                response.raise_for_status()

        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - started_at
            logger.error(
                "Groq inference timed out: model=%s elapsed_seconds=%.1f "
                "timeout_seconds=%.1f",
                self.model,
                elapsed,
                self.timeout_seconds,
            )
            raise LLMTimeoutError(
                f"Groq model '{self.model}' did not finish within "
                f"{self.timeout_seconds:.0f} seconds."
            ) from exc

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            error_body = exc.response.text[:1500]
            message = f"Groq returned HTTP {status_code}: {error_body}"

            if status_code == 413:
                raise LLMPromptTooLargeError(
                    "Groq rejected the request because its input is too large. "
                    "Reduce the prepared workbook profile or prompt size."
                ) from exc

            if status_code in {408, 504}:
                raise LLMTimeoutError(message) from exc

            if status_code in {401, 403, 429} or status_code >= 500:
                raise LLMConnectionError(
                    f"{message} Check the API key, Groq account limits, and provider status."
                ) from exc

            raise LLMResponseError(message) from exc

        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Could not connect to Groq at {self.base_url}: {exc}"
            ) from exc

        except httpx.RequestError as exc:
            raise LLMConnectionError(f"Groq request failed: {exc}") from exc

        elapsed = time.perf_counter() - started_at

        try:
            response_data = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "Groq returned a response that was not valid JSON."
            ) from exc

        if not isinstance(response_data, dict):
            raise LLMResponseError("Groq response must be a JSON object.")

        if response_data.get("error"):
            error = response_data["error"]
            if isinstance(error, dict):
                error_message = str(error.get("message", error))
            else:
                error_message = str(error)
            raise LLMResponseError(
                f"Groq reported an inference error: {error_message[:1000]}"
            )

        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseError("Groq response does not contain any choices.")

        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMResponseError("Groq returned an invalid completion choice.")

        finish_reason = choice.get("finish_reason")
        message_data = choice.get("message")
        if not isinstance(message_data, dict):
            raise LLMResponseError("Groq response does not contain a valid message.")

        content = message_data.get("content")
        if not isinstance(content, str) or not content.strip():
            refusal = message_data.get("refusal")
            if refusal:
                raise LLMResponseError(
                    f"Groq refused to generate the analytics plan: {str(refusal)[:500]}"
                )
            raise LLMResponseError("Groq returned empty response content.")

        if finish_reason == "length":
            raise LLMOutputTruncatedError(
                "Groq stopped before completing the analytics plan because the "
                f"output-token limit ({effective_output_tokens}) was reached. "
                "Increase GROQ_MAX_OUTPUT_TOKENS or simplify the requested plan.",
                raw_output=content,
            )

        if finish_reason not in {"stop", None}:
            raise LLMResponseError(
                f"Groq did not complete the response normally (finish_reason={finish_reason}).",
                raw_output=content,
            )

        try:
            parsed_json = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise LLMResponseError(
                "Groq did not return valid JSON content.",
                raw_output=content,
            ) from exc

        try:
            plan = WorkbookAnalyticsPlan.model_validate(parsed_json)
        except ValidationError as exc:
            error_details = exc.errors(
                include_input=False,
                include_context=False,
                include_url=False,
            )
            raise PlanSchemaValidationError(
                "Groq returned JSON that does not match the analytics plan schema.",
                generated_output=content,
                validation_errors=error_details,
            ) from exc

        usage = response_data.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        logger.info(
            "Groq analytics plan generated: model=%s elapsed_seconds=%.1f "
            "prompt_tokens=%s completion_tokens=%s finish_reason=%s",
            self.model,
            elapsed,
            usage.get("prompt_tokens", "unknown"),
            usage.get("completion_tokens", "unknown"),
            finish_reason or "unknown",
        )
        return plan

    def check_connection(self) -> bool:
        """Return whether the Groq API accepts the configured credentials."""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0),
                trust_env=False,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as client:
                response = client.get(f"{self.base_url}/models")
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


def create_groq_client(model: str | None = None) -> GroqClient:
    """Create the configured Groq client using environment variables."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not configured. Add your Groq API key to the backend environment."
        )

    try:
        timeout_seconds = float(os.getenv("GROQ_TIMEOUT_SECONDS", "120"))
        temperature = float(os.getenv("GROQ_TEMPERATURE", "0.1"))
        context_length = int(
            os.getenv("GROQ_CONTEXT_LENGTH", str(DEFAULT_CONTEXT_LENGTH))
        )
        max_output_tokens = int(os.getenv("GROQ_MAX_OUTPUT_TOKENS", "8192"))
    except ValueError as exc:
        raise ValueError("One or more GROQ numeric settings are invalid.") from exc

    return GroqClient(
        api_key=api_key,
        model=model or os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        base_url=os.getenv("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL),
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        context_length=context_length,
        max_output_tokens=max_output_tokens,
        reasoning_effort=os.getenv("GROQ_REASONING_EFFORT", "none"),
        strict_json_schema=_env_bool("GROQ_STRICT_JSON_SCHEMA", False),
    )
