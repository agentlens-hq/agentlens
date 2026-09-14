#!/usr/bin/env python3
"""Broken OpenAI-style agent captured by AgentLens."""

from __future__ import annotations

from dataclasses import dataclass
import os
import json
from pathlib import Path
import sys
import types
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentlens
from examples.shared_tools import dispatch_tool


@dataclass
class FakeOpenAIChoice:
    finish_reason: str
    message: dict[str, Any]


@dataclass
class FakeOpenAIResponse:
    choices: list[FakeOpenAIChoice]
    usage: dict[str, int]


class FakeOpenAICompletions:
    def create(self, **kwargs: Any) -> FakeOpenAIResponse:
        return FakeOpenAIResponse(
            choices=[
                FakeOpenAIChoice(
                    finish_reason="tool_calls",
                    message={
                        "role": "assistant",
                        "content": "The tools look equivalent, so I will try search_web.",
                        "tool_calls": [
                            {
                                "id": "call_openai_001",
                                "type": "function",
                                "function": {
                                    "name": "search_web",
                                    "arguments": "{\"query\": \"customer:alex renewal status\"}",
                                },
                            }
                        ],
                    },
                )
            ],
            usage={"prompt_tokens": 144, "completion_tokens": 38, "total_tokens": 182},
        )


class FakeOpenAIChat:
    def __init__(self) -> None:
        self.completions = FakeOpenAICompletions()


class FakeOpenAIClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.chat = FakeOpenAIChat()


def install_fake_openai_if_needed() -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    fake_module = types.SimpleNamespace(OpenAI=FakeOpenAIClient)
    sys.modules["openai"] = fake_module


@agentlens.run(name="openai_customer_support_agent")
def run_agent(query: str) -> None:
    import openai

    client = openai.OpenAI()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "find info about a topic",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_db",
                "description": "find info about a topic",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    ]
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": query}],
        tools=tools,
    )

    message = response.choices[0].message
    calls = message.get("tool_calls", []) if isinstance(message, dict) else message.tool_calls or []
    for call in calls:
        data = call if isinstance(call, dict) else call.model_dump()
        function = data["function"]
        tool_input = json.loads(function["arguments"])
        result = dispatch_tool(function["name"], tool_input)
        agentlens.record_tool_result(tool_name=function["name"], input=tool_input,
                                    output=result, tool_use_id=data["id"])


def main() -> None:
    install_fake_openai_if_needed()
    agentlens.init(api_key="al_local")
    run_agent("Find the renewal status for customer:alex using local records.")
    print("Captured run in .agentlens/runs/")
    print("View it with: agentlens runs list")
    print("Then run: agentlens runs show <run_id>")


if __name__ == "__main__":
    main()
