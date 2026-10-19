"""Command-line entry point: `python -m sungrid_copilot.cli <command>`."""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from sungrid_copilot.config import ConfigError, load_settings
from sungrid_copilot.llm import LLMError, get_llm_client
from sungrid_copilot.llm.factory import describe_provider


class _Ping(BaseModel):
    status: str


def check_llm() -> int:
    """Print the provider setup, then make one plain and one JSON call."""
    try:
        settings = load_settings()
        for label, value in describe_provider(settings).items():
            print(f"{label}: {value}")

        client = get_llm_client(settings=settings)
        reply = client.complete(
            "You are a connectivity check.",
            [{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=10,
        )
        print(f"\nReply: {reply.text.strip()!r}")
        print(f"Model: {reply.model}")
        print(f"Tokens: {reply.input_tokens} in / {reply.output_tokens} out")
        print(f"Latency: {reply.latency_s:.2f}s")

        parsed = client.complete_json(
            "You are a connectivity check.",
            [{"role": "user", "content": 'Return a JSON object with "status" set to "ok".'}],
            _Ping,
            max_tokens=50,
        )
        print(f"\nJSON: {parsed.value.model_dump()} ({len(parsed.responses)} attempt(s))")
    except (ConfigError, LLMError) as e:
        print(f"\ncheck-llm failed: {e}", file=sys.stderr)
        return 1
    print("\ncheck-llm OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sungrid_copilot.cli", description="SunGrid Copilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-llm", help="Smoke-test the configured LLM provider")
    args = parser.parse_args(argv)

    if args.command == "check-llm":
        return check_llm()
    return 2


if __name__ == "__main__":
    sys.exit(main())
