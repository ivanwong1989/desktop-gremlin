from __future__ import annotations

import logging
import os

from .config import AppConfig, load_env_file

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


class SearchClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = self._create_client()

    @property
    def is_configured(self) -> bool:
        return self.client is not None

    def _create_client(self):
        if TavilyClient is None:
            logging.warning("tavily-python is not installed; web search is unavailable")
            return None

        load_env_file(self.config.env_file)
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logging.warning("TAVILY_API_KEY is not set; web search is unavailable")
            return None

        return TavilyClient(api_key=api_key)

    def search_web(self, query: str) -> str:
        if self.client is None:
            if TavilyClient is None:
                raise RuntimeError("tavily-python is not installed.")
            raise RuntimeError("TAVILY_API_KEY is not set.")

        try:
            response = self.client.search(
                query=query,
                search_depth="basic",
                max_results=self.config.tavily_max_results,
                include_answer=True,
                timeout=self.config.tavily_timeout_seconds,
            )
        except Exception as exc:
            logging.exception("Tavily search failed")
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        if not isinstance(response, dict):
            logging.error("Invalid Tavily response type: %s", type(response).__name__)
            raise RuntimeError("Tavily returned an invalid response.")

        if not response.get("answer") and not response.get("results"):
            logging.error("Tavily returned empty results: %s", truncate(response, 1500))
            raise RuntimeError("Tavily returned empty search results.")

        return self._format_search_context(query, response)

    def _format_search_context(self, query: str, response: dict) -> str:
        lines = [f"Query: {query}"]
        answer = response.get("answer")
        if answer:
            lines.extend(["", f"Answer: {answer}"])

        results = response.get("results") or []
        if results:
            lines.extend(["", "Top results:"])
        for index, item in enumerate(results[: self.config.tavily_max_results], start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or "Untitled"
            content = item.get("content") or ""
            url = item.get("url") or ""
            lines.append(f"{index}. {title}")
            if content:
                lines.append(f"   {truncate(content, 500)}")
            if url:
                lines.append(f"   URL: {url}")
        return "\n".join(lines)


def with_search_context(user_text: str, search_context: str) -> str:
    return "\n\n".join(
        [
            "User question:",
            user_text,
            "Web search context:",
            search_context,
            "Use the web search context when relevant. If it does not answer the question, say so briefly.",
        ]
    )


def truncate(text, max_chars):
    text = str(text).replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
