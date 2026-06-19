from __future__ import annotations

import logging
from typing import Any

from ..config import AppConfig
from ..search_client import TavilyClient, load_env_file


def web_search(query: str, config: AppConfig) -> dict[str, Any]:
    if not isinstance(query, str):
        return failure("", "Query must be a string.")

    query = query.strip()
    if not query:
        return failure(query, "Query cannot be empty.")

    if len(query) > config.max_search_query_length:
        return failure(query, "Query exceeds the maximum length.")

    if TavilyClient is None:
        return failure(query, "tavily-python is not installed.")

    load_env_file(config.env_file)
    try:
        from os import environ

        api_key = environ.get("TAVILY_API_KEY")
        if not api_key:
            return failure(query, "TAVILY_API_KEY is not set.")

        client = TavilyClient(api_key=api_key)
        logging.info("[Tavily] Search started")
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=config.tavily_max_results,
            include_answer=True,
            include_raw_content=False,
            timeout=config.tavily_timeout_seconds,
        )
    except Exception as exc:
        logging.exception("[Tavily] Search failed")
        return failure(query, f"Tavily search failed: {exc}")

    normalized = normalize_tavily_response(query, response, config)
    logging.info("[Tavily] Search completed with %s results", len(normalized.get("results", [])))
    return normalized


def normalize_tavily_response(query: str, response: Any, config: AppConfig) -> dict[str, Any]:
    if not isinstance(response, dict):
        return failure(query, "Tavily returned an invalid response.")

    answer = response.get("answer") or ""
    results = []
    total_chars = 0

    raw_results = response.get("results") or []
    if not isinstance(raw_results, list):
        return failure(query, "Tavily returned malformed results.")

    for item in raw_results[: config.tavily_max_results]:
        if not isinstance(item, dict):
            continue

        title = truncate(str(item.get("title") or "Untitled"), 300)
        url = truncate(str(item.get("url") or ""), 1000)
        content = truncate(str(item.get("content") or ""), config.max_result_content_chars)

        projected = total_chars + len(title) + len(url) + len(content)
        if projected > config.max_total_tool_content_chars:
            remaining = max(0, config.max_total_tool_content_chars - total_chars - len(title) - len(url))
            content = truncate(content, remaining)

        results.append({"title": title, "url": url, "content": content})
        total_chars += len(title) + len(url) + len(content)
        if total_chars >= config.max_total_tool_content_chars:
            break

    if not answer and not results:
        return failure(query, "Tavily returned empty search results.")

    return {
        "ok": True,
        "query": query,
        "answer": truncate(str(answer), config.max_result_content_chars),
        "results": results,
    }


def failure(query: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "query": query,
        "error": error,
        "results": [],
    }


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    text = str(text).replace("\r", " ").replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."

