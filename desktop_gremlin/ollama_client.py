from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Callable
from urllib.parse import urlparse

import requests

from .config import AppConfig
from .models import ChatMessage, StreamDelta


_OLLAMA_START_LOCK = threading.Lock()
StatusCallback = Callable[[str], None]


class OllamaClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.started_ollama_process: subprocess.Popen | None = None

    def ensure_ready(
        self,
        config: AppConfig | None = None,
        preload_model: bool = False,
        status_callback: StatusCallback | None = None,
    ) -> None:
        active_config = config or self.config
        update_status(status_callback, "Checking Ollama...")
        if not self._is_ollama_ready(active_config):
            update_status(status_callback, "Starting Ollama...")
            if not self._try_start_ollama(active_config):
                raise RuntimeError("Ollama does not seem to be running.")

        if preload_model:
            update_status(status_callback, f"Loading model: {active_config.model}")
            self._preload_model(active_config)
            update_status(status_callback, f"Model ready: {active_config.model}")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        config: AppConfig | None = None,
    ):
        active_config = config or self.config
        url = active_config.ollama_base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": active_config.model,
            "stream": True,
            "think": active_config.think,
            "messages": self._to_payload_messages(messages, active_config),
            "options": active_config.to_ollama_options(),
            "keep_alive": active_config.model_keep_alive,
        }
        if tools:
            payload["tools"] = tools

        yielded_any = False
        for attempt in range(2):
            try:
                logging.info(
                    "Sending streaming Ollama chat request: url=%s model=%s tools=%s num_ctx=%s num_predict=%s think=%s",
                    url,
                    active_config.model,
                    len(tools or []),
                    active_config.num_ctx,
                    active_config.num_predict,
                    active_config.think,
                )
                with requests.post(
                    url,
                    json=payload,
                    timeout=active_config.request_timeout_seconds,
                    stream=True,
                ) as response:
                    logging.info(
                        "Ollama HTTP response: status=%s content_type=%s",
                        response.status_code,
                        response.headers.get("content-type", ""),
                    )
                    if response.status_code == 404:
                        detail = truncate(response.text.strip(), 1000)
                        raise RuntimeError(self._model_not_found_message(active_config, detail))

                    try:
                        response.raise_for_status()
                    except requests.exceptions.HTTPError as exc:
                        detail = truncate(response.text.strip(), 1000)
                        if "not found" in detail.lower() or "model" in detail.lower():
                            raise RuntimeError(self._model_not_found_message(active_config, detail)) from exc
                        raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {detail}") from exc

                    for raw_line in response.iter_lines(decode_unicode=True):
                        if not raw_line:
                            continue
                        try:
                            chunk = json.loads(raw_line)
                        except ValueError:
                            logging.warning("Skipping invalid Ollama stream line: %s", truncate(raw_line, 500))
                            continue

                        ollama_error = chunk.get("error")
                        if isinstance(ollama_error, str) and ollama_error.strip():
                            raise RuntimeError(f"Ollama error: {ollama_error.strip()}")

                        yielded_any = True
                        yield self._parse_stream_delta(chunk)
                        if chunk.get("done"):
                            break
                    return
            except requests.exceptions.ConnectionError as exc:
                if attempt == 0 and not yielded_any and self._try_start_ollama(active_config):
                    continue
                raise RuntimeError("Ollama does not seem to be running.") from exc
            except requests.exceptions.Timeout as exc:
                raise RuntimeError("Ollama took too long to answer.") from exc
            except requests.exceptions.RequestException as exc:
                raise RuntimeError(f"Ollama request failed: {exc}") from exc

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        stream: bool = False,
        config: AppConfig | None = None,
    ) -> dict:
        active_config = config or self.config
        url = active_config.ollama_base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": active_config.model,
            "stream": stream,
            "think": active_config.think,
            "messages": self._to_payload_messages(messages, active_config),
            "options": active_config.to_ollama_options(),
            "keep_alive": active_config.model_keep_alive,
        }
        if tools:
            payload["tools"] = tools

        for attempt in range(2):
            try:
                logging.info(
                    "Sending Ollama chat request: url=%s model=%s stream=%s tools=%s num_ctx=%s num_predict=%s think=%s",
                    url,
                    active_config.model,
                    stream,
                    len(tools or []),
                    active_config.num_ctx,
                    active_config.num_predict,
                    active_config.think,
                )
                response = requests.post(
                    url,
                    json=payload,
                    timeout=active_config.request_timeout_seconds,
                )
                logging.info(
                    "Ollama HTTP response: status=%s content_type=%s",
                    response.status_code,
                    response.headers.get("content-type", ""),
                )
                if response.status_code == 404:
                    detail = truncate(response.text.strip(), 1000)
                    raise RuntimeError(self._model_not_found_message(active_config, detail))

                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as exc:
                    detail = truncate(response.text.strip(), 1000)
                    if "not found" in detail.lower() or "model" in detail.lower():
                        raise RuntimeError(self._model_not_found_message(active_config, detail)) from exc
                    raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {detail}") from exc

                try:
                    response_json = response.json()
                except ValueError as exc:
                    raise RuntimeError("Ollama returned invalid JSON.") from exc

                if not isinstance(response_json, dict):
                    raise RuntimeError("Ollama returned an invalid response.")
                logging.debug("Ollama response message: %s", response_json.get("message"))
                return response_json
            except requests.exceptions.ConnectionError as exc:
                if attempt == 0 and self._try_start_ollama(active_config):
                    continue
                raise RuntimeError("Ollama does not seem to be running.") from exc
            except requests.exceptions.Timeout as exc:
                raise RuntimeError("Ollama took too long to answer.") from exc
            except requests.exceptions.RequestException as exc:
                raise RuntimeError(f"Ollama request failed: {exc}") from exc

        raise RuntimeError("Ollama request failed after startup retry.")

    def _try_start_ollama(self, config: AppConfig) -> bool:
        if not config.auto_start_ollama:
            return False
        if not is_local_ollama_url(config.ollama_base_url):
            logging.info("Skipping Ollama auto-start for non-local URL: %s", config.ollama_base_url)
            return False

        with _OLLAMA_START_LOCK:
            if self._is_ollama_ready(config):
                return True

            command = config.ollama_command.strip() or "ollama"
            executable = shutil.which(command)
            if executable is None:
                logging.warning("Cannot auto-start Ollama; command not found: %s", command)
                return False

            launch_args = [executable, "serve"]
            logging.info("Ollama is not reachable; launching: %s", launch_args)
            try:
                startupinfo = None
                creationflags = 0
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    if len(launch_args) > 1:
                        creationflags = subprocess.CREATE_NO_WINDOW
                self.started_ollama_process = subprocess.Popen(
                    launch_args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                    startupinfo=startupinfo,
                    env=os.environ.copy(),
                )
            except OSError as exc:
                logging.warning("Failed to launch Ollama: %s", exc)
                return False

            return self._wait_for_ollama(config)

    def shutdown_started_ollama(self) -> bool:
        process = self.started_ollama_process
        if process is None:
            return False
        if process.poll() is not None:
            self.started_ollama_process = None
            return True

        logging.info("Stopping app-started Ollama process: pid=%s", process.pid)
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logging.warning("Ollama process did not exit after terminate; killing pid=%s", process.pid)
            process.kill()
            process.wait(timeout=5)
        except OSError as exc:
            logging.warning("Failed to stop Ollama process pid=%s: %s", process.pid, exc)
            return False
        finally:
            self.started_ollama_process = None
        return True

    def shutdown_ollama_server(self, config: AppConfig | None = None) -> None:
        active_config = config or self.config
        if not active_config.stop_ollama_server_on_exit:
            return
        if self.shutdown_started_ollama():
            return
        if os.name != "nt":
            logging.info("No app-started Ollama process handle; skipping server shutdown on non-Windows")
            return
        if not is_local_ollama_url(active_config.ollama_base_url):
            logging.info("Skipping Ollama server shutdown for non-local URL: %s", active_config.ollama_base_url)
            return

        port = port_from_url(active_config.ollama_base_url)
        pid = windows_pid_listening_on_port(port)
        if pid is None:
            logging.info("No Ollama server listener found on port %s during shutdown", port)
            return

        logging.info("Stopping Ollama server listener on port %s: pid=%s", port, pid)
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            logging.warning("Timed out stopping Ollama server pid=%s", pid)
            return
        except OSError as exc:
            logging.warning("Failed to stop Ollama server pid=%s: %s", pid, exc)
            return

        if completed.returncode != 0:
            logging.warning("taskkill exited with status %s for Ollama server pid=%s", completed.returncode, pid)

    def stop_model(self, config: AppConfig | None = None) -> None:
        active_config = config or self.config
        model = active_config.model.strip()
        if not model:
            return

        command = active_config.ollama_command.strip() or "ollama"
        executable = shutil.which(command)
        if executable is None:
            logging.warning("Cannot stop Ollama model; command not found: %s", command)
            return

        env = os.environ.copy()
        env.setdefault("OLLAMA_HOST", active_config.ollama_base_url)
        logging.info("Stopping Ollama model before exit: model=%s host=%s", model, env.get("OLLAMA_HOST"))
        try:
            completed = subprocess.run(
                [executable, "stop", model],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            logging.warning("Timed out stopping Ollama model before exit: %s", model)
            return
        except OSError as exc:
            logging.warning("Failed to stop Ollama model before exit: %s", exc)
            return

        if completed.returncode != 0:
            logging.warning("ollama stop exited with status %s for model %s", completed.returncode, model)

    def _wait_for_ollama(self, config: AppConfig) -> bool:
        deadline = time.monotonic() + max(1, config.ollama_startup_timeout_seconds)
        while time.monotonic() < deadline:
            if self._is_ollama_ready(config):
                logging.info("Ollama is ready after auto-start")
                return True
            time.sleep(0.5)
        logging.warning("Ollama did not become ready within %s seconds", config.ollama_startup_timeout_seconds)
        return False

    def _is_ollama_ready(self, config: AppConfig) -> bool:
        url = config.ollama_base_url.rstrip("/") + "/api/tags"
        try:
            response = requests.get(url, timeout=1)
        except requests.exceptions.RequestException:
            return False
        return response.status_code == 200

    def _preload_model(self, config: AppConfig) -> None:
        url = config.ollama_base_url.rstrip("/") + "/api/chat"
        options = config.to_ollama_options()
        options["num_predict"] = min(16, max(1, config.num_predict))
        payload = {
            "model": config.model,
            "stream": False,
            "think": config.think,
            "messages": [
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": "Warm up the model. Reply with OK."},
            ],
            "options": options,
            "keep_alive": config.model_keep_alive,
        }
        try:
            logging.info(
                "Preloading Ollama model: url=%s model=%s keep_alive=%s",
                url,
                config.model,
                config.model_keep_alive,
            )
            response = requests.post(url, json=payload, timeout=config.request_timeout_seconds)
            logging.info(
                "Ollama preload response: status=%s content_type=%s",
                response.status_code,
                response.headers.get("content-type", ""),
            )
            if response.status_code == 404:
                detail = truncate(response.text.strip(), 1000)
                raise RuntimeError(self._model_not_found_message(config, detail))
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise RuntimeError("Ollama took too long to load the model.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError("Ollama stopped while loading the model.") from exc
        except requests.exceptions.HTTPError as exc:
            detail = truncate(response.text.strip(), 1000)
            raise RuntimeError(f"Ollama model preload failed with HTTP {response.status_code}: {detail}") from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Ollama model preload failed: {exc}") from exc

    def _model_not_found_message(self, config: AppConfig, detail: str) -> str:
        available = self._available_model_names(config)
        if available:
            server_state = f" Connected server models: {', '.join(available)}."
        else:
            server_state = " Connected server reports no installed models."

        models_path = os.environ.get("OLLAMA_MODELS")
        if models_path:
            server_state += f" OLLAMA_MODELS={models_path}."
        else:
            server_state += " OLLAMA_MODELS is not set for this app."

        return f"Model not found on {config.ollama_base_url}: {config.model}. {detail}{server_state}"

    def _available_model_names(self, config: AppConfig) -> list[str]:
        url = config.ollama_base_url.rstrip("/") + "/api/tags"
        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError):
            return []

        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []
        names = []
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("name"), str):
                names.append(model["name"])
        return names

    def _to_payload_messages(self, messages: list[ChatMessage], config: AppConfig) -> list[dict]:
        payload_messages: list[dict] = [{"role": "system", "content": config.system_prompt}]
        for message in messages:
            if message.role == "system":
                continue
            item = {"role": message.role, "content": message.content}
            if message.role == "user" and message.images:
                item["images"] = list(message.images)
            if message.role == "assistant" and message.tool_calls:
                item["tool_calls"] = list(message.tool_calls)
            if message.role == "tool" and message.tool_name:
                item["tool_name"] = message.tool_name
            payload_messages.append(item)
        return payload_messages

    def _parse_stream_delta(self, chunk: dict) -> StreamDelta:
        visible = chunk.get("response") or ""
        thinking = chunk.get("thinking") or chunk.get("thought") or ""

        message = chunk.get("message")
        if isinstance(message, dict):
            visible += message.get("content") or ""
            thinking += message.get("thinking") or message.get("thought") or ""
            tool_calls = message.get("tool_calls") or []
        else:
            tool_calls = []

        return StreamDelta(
            content=visible,
            thinking=thinking,
            tool_calls=tool_calls if isinstance(tool_calls, list) else [],
            done=bool(chunk.get("done")),
            prompt_eval_count=chunk.get("prompt_eval_count"),
            eval_count=chunk.get("eval_count"),
        )


def truncate(text, max_chars):
    text = str(text).replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def is_local_ollama_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def port_from_url(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80


def windows_pid_listening_on_port(port: int) -> int | None:
    script = (
        f"$conn = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -First 1; "
        "if ($conn) { [Console]::Out.Write($conn.OwningProcess) }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.warning("Could not inspect Windows TCP listener on port %s: %s", port, exc)
        return None

    if completed.returncode != 0:
        logging.warning("Get-NetTCPConnection failed for port %s: %s", port, truncate(completed.stderr, 500))
        return None

    output = completed.stdout.strip()
    if not output:
        return None
    try:
        return int(output)
    except ValueError:
        logging.warning("Invalid listener PID for port %s: %s", port, output)
        return None


def update_status(callback: StatusCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
