from __future__ import annotations

import ast
from dataclasses import dataclass
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..config import AppConfig


ALLOWED_IMPORT_ROOTS = {
    "collections",
    "datetime",
    "decimal",
    "fractions",
    "functools",
    "itertools",
    "json",
    "math",
    "operator",
    "re",
    "statistics",
    "string",
}

BLOCKED_CALL_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "quit",
    "vars",
}

BLOCKED_ATTR_NAMES = {
    "popen",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "run",
    "startfile",
    "system",
    "unlink",
}


@dataclass
class ValidationIssue:
    message: str
    line: int | None = None

    def format(self) -> str:
        if self.line is None:
            return self.message
        return f"Line {self.line}: {self.message}"


def python_runner(code: str, config: AppConfig) -> dict[str, Any]:
    if not isinstance(code, str):
        return failure("Code must be a string.")

    code = code.strip()
    if not code:
        return failure("Code cannot be empty.")

    if len(code) > config.max_python_code_chars:
        return failure(f"Code exceeds {config.max_python_code_chars} characters.")

    issue = validate_code(code)
    if issue is not None:
        return failure(issue.format(), code=code)

    try:
        with tempfile.TemporaryDirectory(prefix="desktop_gremlin_python_") as temp_dir:
            script_path = Path(temp_dir) / "generated_code.py"
            script_path.write_text(code, encoding="utf-8")
            logging.info("[PythonRunner] Running generated code")
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=config.python_runner_timeout_seconds,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        stdout = truncate(exc.stdout or "", config.max_python_output_chars)
        stderr = truncate(exc.stderr or "", config.max_python_output_chars)
        return {
            "ok": False,
            "error": f"Python code timed out after {config.python_runner_timeout_seconds} seconds.",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": None,
            "script": "generated_code.py",
        }
    except Exception as exc:
        logging.exception("[PythonRunner] Execution failed")
        return failure(f"Python runner failed: {exc}", code=code)

    stdout = truncate(completed.stdout, config.max_python_output_chars)
    stderr = truncate(completed.stderr, config.max_python_output_chars)
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": f"Python exited with status {completed.returncode}.",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": completed.returncode,
            "script": "generated_code.py",
        }

    return {
        "ok": True,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": completed.returncode,
        "script": "generated_code.py",
    }


def validate_code(code: str) -> ValidationIssue | None:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return ValidationIssue(f"Syntax error: {exc.msg}", exc.lineno)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            issue = validate_import(node)
            if issue is not None:
                return issue
        elif isinstance(node, ast.Call):
            issue = validate_call(node)
            if issue is not None:
                return issue
        elif isinstance(node, ast.Attribute):
            issue = validate_attribute(node)
            if issue is not None:
                return issue
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            return ValidationIssue("Dunder names are not allowed.", getattr(node, "lineno", None))

    return None


def validate_import(node: ast.Import | ast.ImportFrom) -> ValidationIssue | None:
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
        line = node.lineno
    else:
        names = [node.module or ""]
        line = node.lineno

    for name in names:
        root = name.split(".", 1)[0]
        if root not in ALLOWED_IMPORT_ROOTS:
            return ValidationIssue(f"Import is not allowed: {root}", line)
    return None


def validate_call(node: ast.Call) -> ValidationIssue | None:
    if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
        return ValidationIssue(f"Call is not allowed: {node.func.id}", node.lineno)

    if isinstance(node.func, ast.Attribute) and node.func.attr.lower() in BLOCKED_ATTR_NAMES:
        return ValidationIssue(f"Method call is not allowed: {node.func.attr}", node.lineno)

    return None


def validate_attribute(node: ast.Attribute) -> ValidationIssue | None:
    if node.attr.startswith("__"):
        return ValidationIssue("Dunder attributes are not allowed.", node.lineno)
    return None


def failure(error: str, code: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "script": "generated_code.py" if code else None,
    }


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... [truncated]"
