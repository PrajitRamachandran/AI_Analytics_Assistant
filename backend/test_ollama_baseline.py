
"""Measure raw Ollama inference without the analytics JSON schema."""

import time
import httpx


def main():
    url = "http://localhost:11434/api/chat"

    payload = {
        "model": "qwen3.5:4b",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Return a JSON object with two fields: "
                    "'status' set to 'success' and "
                    "'message' set to 'Qwen is working'."
                ),
            }
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,
            "num_predict": 128,
        },
    }

    print("Testing raw Qwen inference...")
    print("Model: qwen3.5:4b")
    print("Context: 4096")
    print("Maximum output tokens: 128")

    start = time.perf_counter()

    try:
        with httpx.Client(timeout=300.0, trust_env=False) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        elapsed = time.perf_counter() - start
        result = response.json()

        print("\nInference completed!")
        print(f"Elapsed time: {elapsed:.2f} seconds")

        print("\nGenerated response:")
        print(result.get("message", {}).get("content"))

        print("\nOllama metrics:")
        for key in (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "prompt_eval_duration",
            "eval_count",
            "eval_duration",
        ):
            if key in result:
                print(f"{key}: {result[key]}")

    except httpx.TimeoutException:
        print("\nERROR: Ollama did not respond within 300 seconds.")

    except httpx.HTTPStatusError as exc:
        print("\nHTTP ERROR:", exc.response.status_code)
        print(exc.response.text)

    except httpx.RequestError as exc:
        print("\nCONNECTION ERROR:", exc)


if __name__ == "__main__":
    main()
