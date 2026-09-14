"""Shared fake tool implementations used by the broken-agent examples."""

from __future__ import annotations

from typing import Any


def search_web(query: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "Network access disabled. Customer records are only available in query_db.",
        "query": query,
    }


def query_db(query: str) -> dict[str, Any]:
    return {"status": "success", "renewal_status": "active", "query": query}


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tools = {"search_web": search_web, "query_db": query_db}
    if name not in tools:
        return {"error": f"Unknown tool: {name}"}
    return tools[name](**arguments)
