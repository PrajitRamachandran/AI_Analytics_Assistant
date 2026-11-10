
"""Inspect Ollama's structured-output completion metadata."""

import time
import httpx

from test_module4_inference import create_sample_profile
from app.modules.analytics_planner.profile_preparation import (
    DatasetProfilePreparer,
)
from app.modules.analytics_planner.prompt_builder import (
    AnalyticsPromptBuilder,
)
from app.schemas.analytics_plan import WorkbookAnalyticsPlan


def main():
    profile = create_sample_profile()

    prepared = DatasetProfilePreparer().prepare(profile)
    messages = AnalyticsPromptBuilder().build_messages(prepared)

    payload = {
        "model": "qwen3.5:4b",
        "messages": messages,
        "stream": False,
        "format": WorkbookAnalyticsPlan.model_json_schema(),
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,
            "num_predict": 1024,
        },
    }

    print("Sending diagnostic request to Ollama...")
    start = time.perf_counter()

    with httpx.Client(timeout=360.0, trust_env=False) as client:
        response = client.post(
            "http://localhost:11434/api/chat",
            json=payload,
        )
        response.raise_for_status()

    result = response.json()
    elapsed = time.perf_counter() - start

    message = result.get("message", {})
    content = message.get("content", "")

    print("\n--- INFERENCE METADATA ---")
    print("Elapsed seconds:", round(elapsed, 2))
    print("Done:", result.get("done"))
    print("Done reason:", result.get("done_reason"))
    print("Prompt tokens:", result.get("prompt_eval_count"))
    print("Generated tokens:", result.get("eval_count"))
    print("Content characters:", len(content))

    print("\n--- LAST 800 CHARACTERS ---")
    print(content[-800:])

    print("\n--- JSON STATUS ---")
    try:
        import json
        json.loads(content)
        print("Valid JSON")
    except json.JSONDecodeError as exc:
        print("Invalid JSON:", exc)


if __name__ == "__main__":
    main()
