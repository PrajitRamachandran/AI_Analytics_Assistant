
"""Test Module 4 with resource-conscious Ollama settings."""

import json
import time

from app.modules.analytics_planner.analytics_planner import AnalyticsPlanner
from app.modules.analytics_planner.ollama_client import OllamaClient

from test_module4_inference import create_sample_profile


def main():
    print("=" * 60)
    print("MODULE 4 - TUNED INFERENCE TEST")
    print("=" * 60)

    profile = create_sample_profile()

    client = OllamaClient(
        model="qwen3.5:4b",
        timeout_seconds=300,
        context_length=4096,
        max_output_tokens=1024,
        temperature=0.1,
        disable_thinking=True,
    )

    planner = AnalyticsPlanner(ollama_client=client)

    print("\nConfiguration:")
    print("Context length: 4096")
    print("Maximum output: 1024 tokens")
    print("Timeout: 300 seconds")
    print("\nStarting inference...")

    start = time.perf_counter()

    try:
        plan = planner.generate_plan(profile)

        elapsed = time.perf_counter() - start

        print("\nINFERENCE SUCCESS!")
        print(f"Elapsed time: {elapsed:.2f} seconds")

        result = plan.model_dump(mode="json")

        print("\nGenerated plan:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        print("\nOperation count:", len(plan.operations))
        print("KPI count:", len(plan.kpis))
        print("Visualization count:", len(plan.visualizations))

        print("\nTUNED INFERENCE TEST: SUCCESS")

    except Exception as exc:
        elapsed = time.perf_counter() - start

        print("\nINFERENCE FAILED")
        print(f"Elapsed time: {elapsed:.2f} seconds")
        print("Error type:", type(exc).__name__)
        print("Error:", str(exc))


if __name__ == "__main__":
    main()
