"""LLM provider and model discovery/selection endpoints."""
from __future__ import annotations
import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.core.dataset_state import ensure_state_schema, get_selected_model, set_selected_model

router = APIRouter(prefix="/api/models", tags=["LLM Models"])

class ModelSelection(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)

@router.get("")
def list_models() -> dict:
    ensure_state_schema()
    models = []
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        response = httpx.get(f"{ollama_url}/api/tags", timeout=4.0)
        response.raise_for_status()
        for item in response.json().get("models", []):
            name = item.get("name")
            if name:
                models.append({"provider": "ollama", "model": name, "available": True})
    except (httpx.HTTPError, ValueError):
        pass

    groq_model = os.getenv("GROQ_MODEL")
    if os.getenv("GROQ_API_KEY"):
        if groq_model:
            models.append({"provider": "groq", "model": groq_model, "available": True})
        else:
            models.append({"provider": "groq", "model": "llama-3.3-70b-versatile", "available": True})
    return {"models": models, "selected": get_selected_model(),
            "providers": [
                {"id": "ollama", "type": "local", "configured": True},
                {"id": "groq", "type": "cloud", "configured": bool(os.getenv("GROQ_API_KEY"))},
            ]}

@router.put("/selection")
def select_model(selection: ModelSelection) -> dict:
    try:
        selected = set_selected_model(selection.provider, selection.model)
        # Validate provider config early; this checks required credentials and config.
        from app.modules.analytics_planner.llm_client import create_llm_client
        client = create_llm_client(selected["provider"], selected["model"])
        return {"status": "success", "selected": selected,
                "connection_ready": client.check_connection()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to configure selected model: {exc}") from exc
