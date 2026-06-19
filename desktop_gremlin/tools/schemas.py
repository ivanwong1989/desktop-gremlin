from __future__ import annotations


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current, recent, changing, niche, "
            "or externally verifiable information. Use this for current news, "
            "prices, schedules, laws, software versions, product specifications, "
            "sports results, public office holders, recent company information, "
            "and facts that may have changed after training."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A concise standalone web search query containing the "
                        "important subject and any relevant date, country, "
                        "location, version, or recency terms."
                    ),
                }
            },
            "required": ["query"],
        },
    },
}


PYTHON_RUNNER_TOOL = {
    "type": "function",
    "function": {
        "name": "python_runner",
        "description": (
            "Run simple, self-contained Python code for exact calculations, "
            "small algorithms, data parsing, validation, or deterministic checks. "
            "The code must print the values needed for the answer. Do not use this "
            "for file access, network access, package installation, subprocesses, "
            "secrets, or operating-system operations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Self-contained Python code to execute. It should use only "
                        "standard calculation/parsing libraries and print the final "
                        "values needed for the answer."
                    ),
                }
            },
            "required": ["code"],
        },
    },
}
