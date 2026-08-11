from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from llm.provider_config import DEEPSEEK_V4_FLASH_MODEL, normalize_model_name


def read_api_key_file(path: str | os.PathLike[str] | None) -> str:
    if not path:
        return ""
    key_path = Path(path).expanduser()
    if not key_path.exists():
        return ""
    return key_path.read_text(encoding="utf-8").strip()


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_key_file: str | os.PathLike[str] | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: int = 60,
    ):
        env_key_file = os.getenv("DEEPSEEK_API_KEY_FILE")
        self.api_key = (
            api_key
            or read_api_key_file(api_key_file)
            or read_api_key_file(env_key_file)
            or os.getenv("DEEPSEEK_API_KEY")
        )
        if not self.api_key:
            raise RuntimeError("DeepSeek API key is not configured")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.default_model = normalize_model_name(
            default_model or os.getenv("DEEPSEEK_DEFAULT_MODEL") or DEEPSEEK_V4_FLASH_MODEL
        )
        self.timeout = timeout
        self._timing_local = threading.local()
        self.last_timing: dict[str, Any] = {}

    @property
    def last_timing(self) -> dict[str, Any]:
        return getattr(self._timing_local, "value", {})

    @last_timing.setter
    def last_timing(self, value: dict[str, Any]) -> None:
        self._timing_local.value = value

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> tuple[dict, dict | None, str]:
        started_at = time.perf_counter()
        selected_model = normalize_model_name(model or self.default_model)
        self.last_timing = {
            "model": selected_model,
            "max_tokens": max_tokens,
            "timeout_seconds": self.timeout,
        }
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        payload_started_at = time.perf_counter()
        payload_bytes = json.dumps(payload).encode("utf-8")
        self.last_timing["payload_build_seconds"] = round(time.perf_counter() - payload_started_at, 3)
        self.last_timing["request_bytes"] = len(payload_bytes)
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            open_started_at = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_timing["http_open_seconds"] = round(time.perf_counter() - open_started_at, 3)
                self.last_timing["http_status"] = getattr(response, "status", "")
                read_started_at = time.perf_counter()
                body_bytes = response.read()
                self.last_timing["response_read_seconds"] = round(time.perf_counter() - read_started_at, 3)
                self.last_timing["response_bytes"] = len(body_bytes)
                body = body_bytes.decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {details}") from exc
        except Exception:
            self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
            raise

        parse_started_at = time.perf_counter()
        data = json.loads(body)
        raw_content = data["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        usage = data.get("usage")
        self.last_timing["json_parse_seconds"] = round(time.perf_counter() - parse_started_at, 3)
        self.last_timing["prompt_tokens"] = (usage or {}).get("prompt_tokens", "")
        self.last_timing["completion_tokens"] = (usage or {}).get("completion_tokens", "")
        self.last_timing["total_tokens"] = (usage or {}).get("total_tokens", "")
        choices = data.get("choices") or []
        if choices:
            self.last_timing["finish_reason"] = choices[0].get("finish_reason", "")
        self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
        return parsed, usage, raw_content

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> tuple[str, dict | None]:
        data = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            response_format=None,
        )
        raw_content = data["choices"][0]["message"]["content"]
        return raw_content, data.get("usage")

    def _chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None,
        max_tokens: int,
        response_format: dict[str, Any] | None,
    ) -> dict:
        started_at = time.perf_counter()
        selected_model = normalize_model_name(model or self.default_model)
        self.last_timing = {
            "model": selected_model,
            "max_tokens": max_tokens,
            "timeout_seconds": self.timeout,
        }
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        payload_started_at = time.perf_counter()
        payload_bytes = json.dumps(payload).encode("utf-8")
        self.last_timing["payload_build_seconds"] = round(time.perf_counter() - payload_started_at, 3)
        self.last_timing["request_bytes"] = len(payload_bytes)
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            open_started_at = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_timing["http_open_seconds"] = round(time.perf_counter() - open_started_at, 3)
                self.last_timing["http_status"] = getattr(response, "status", "")
                read_started_at = time.perf_counter()
                body_bytes = response.read()
                self.last_timing["response_read_seconds"] = round(time.perf_counter() - read_started_at, 3)
                self.last_timing["response_bytes"] = len(body_bytes)
                body = body_bytes.decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {details}") from exc
        except Exception:
            self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
            raise

        parse_started_at = time.perf_counter()
        data = json.loads(body)
        usage = data.get("usage")
        self.last_timing["json_parse_seconds"] = round(time.perf_counter() - parse_started_at, 3)
        self.last_timing["prompt_tokens"] = (usage or {}).get("prompt_tokens", "")
        self.last_timing["completion_tokens"] = (usage or {}).get("completion_tokens", "")
        self.last_timing["total_tokens"] = (usage or {}).get("total_tokens", "")
        choices = data.get("choices") or []
        if choices:
            self.last_timing["finish_reason"] = choices[0].get("finish_reason", "")
        self.last_timing["total_seconds"] = round(time.perf_counter() - started_at, 3)
        return data
