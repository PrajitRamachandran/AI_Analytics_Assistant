"""Provider-neutral errors shared by analytics-plan generators."""

from __future__ import annotations

from typing import Any


class PlanSchemaValidationError(Exception):
    """A generated JSON plan failed the shared Pydantic plan schema.

    Providers should raise this error (or a subclass) with the invalid model
    output and safe validation details so the planner can request one bounded
    correction without depending on a specific LLM provider.
    """

    def __init__(
        self,
        message: str,
        *,
        generated_output: str,
        validation_errors: list[dict[str, Any]],
    ) -> None:
        super().__init__(message)
        self.generated_output = generated_output
        self.validation_errors = validation_errors
