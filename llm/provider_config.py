from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProviderConfig:
    provider: str
    api_key_file: str = ""
    base_url: str = ""
    default_model: str = ""
    default_batch_size: int = 1
    timeout_seconds: int = 90
    target_content_count: int = 500
    target_total_seconds: int = 120
    capacity_note: str = ""


def load_provider_config(
    config_path: str | Path,
    provider: str,
    api_key_file_override: str | None = None,
) -> ProviderConfig:
    path = Path(config_path).expanduser()
    if not path.exists():
        return ProviderConfig(provider=provider, api_key_file=api_key_file_override or "")

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    providers = payload.get("providers", {})
    selected = provider or payload.get("default_provider", "")
    if not selected:
        raise ValueError("LLM provider is not configured")
    data = providers.get(selected)
    if not isinstance(data, dict):
        raise ValueError(f"LLM provider is not defined in config: {selected}")

    return ProviderConfig(
        provider=selected,
        api_key_file=api_key_file_override or str(data.get("api_key_file", "")),
        base_url=str(data.get("base_url", "")),
        default_model=str(data.get("default_model", "")),
        default_batch_size=int(data.get("default_batch_size") or data.get("batch_size") or 1),
        timeout_seconds=int(data.get("timeout_seconds") or data.get("timeout") or 90),
        target_content_count=int(data.get("target_content_count") or 500),
        target_total_seconds=int(data.get("target_total_seconds") or 120),
        capacity_note=str(data.get("capacity_note", "")),
    )
