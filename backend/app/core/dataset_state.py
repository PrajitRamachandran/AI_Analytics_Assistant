"""Persistent dataset-stage cache and model-selection metadata."""
from __future__ import annotations
import json
import pickle
from typing import Any
from app.core.database import get_db_connection

def ensure_state_schema() -> None:
    """Apply additive, backwards-compatible PostgreSQL migrations."""
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE datasets
                    ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64),
                    ADD COLUMN IF NOT EXISTS processing_result JSONB,\n                    ADD COLUMN IF NOT EXISTS processing_artifact BYTEA,
                    ADD COLUMN IF NOT EXISTS understanding_result JSONB,
                    ADD COLUMN IF NOT EXISTS analytics_result JSONB,
                    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS understood_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS analysed_at TIMESTAMPTZ;
                CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_content_sha256
                    ON datasets (content_sha256) WHERE content_sha256 IS NOT NULL;
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

def json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value

def save_dataset_stage(dataset_id: str, column: str, value: Any, timestamp_column: str) -> None:
    if column not in {"processing_result", "understanding_result", "analytics_result"}:
        raise ValueError("Unsupported dataset stage.")
    if timestamp_column not in {"processed_at", "understood_at", "analysed_at"}:
        raise ValueError("Unsupported stage timestamp.")
    ensure_state_schema()
    payload = json.dumps(json_value(value), default=str)
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""UPDATE datasets SET {column} = %s::jsonb, {timestamp_column} = NOW()
                    {", processing_artifact = NULL, understanding_result = NULL, analytics_result = NULL, understood_at = NULL, analysed_at = NULL" if column == "processing_result" else ""}
                    {", analytics_result = NULL, analysed_at = NULL" if column == "understanding_result" else ""}
                    WHERE dataset_id = %s""",
                (payload, dataset_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Dataset not found while saving stage output.")

def get_selected_model() -> dict:
    ensure_state_schema()
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'llm_selection'")
            row = cursor.fetchone()
    return row[0] if row else {"provider": None, "model": None}

def set_selected_model(provider: str, model: str) -> dict:
    provider, model = provider.strip().lower(), model.strip()
    if provider not in {"ollama", "groq"} or not model:
        raise ValueError("Supported providers are ollama and groq; model is required.")
    ensure_state_schema()
    value = {"provider": provider, "model": model}
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO app_settings (setting_key, setting_value)
                VALUES ('llm_selection', %s::jsonb)
                ON CONFLICT (setting_key) DO UPDATE
                SET setting_value = EXCLUDED.setting_value, updated_at = NOW()
            """, (json.dumps(value),))
    return value


def save_processing_artifact(dataset_id: str, processing_result: Any) -> None:
    """Persist the trusted, server-generated processing object for downstream stages."""
    ensure_state_schema()
    artifact = pickle.dumps(processing_result, protocol=pickle.HIGHEST_PROTOCOL)
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE datasets SET processing_artifact = %s WHERE dataset_id = %s",
                (artifact, dataset_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Dataset not found while saving processing artifact.")

def load_processing_artifact(dataset_id: str) -> Any | None:
    """Load an application-generated artifact; never unpickle user-supplied bytes."""
    ensure_state_schema()
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT processing_artifact FROM datasets WHERE dataset_id = %s",
                (dataset_id,),
            )
            row = cursor.fetchone()
    if not row or not row[0]:
        return None
    return pickle.loads(row[0])
