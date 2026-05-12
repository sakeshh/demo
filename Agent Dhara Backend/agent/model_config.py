from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional


Provider = Literal["azure_openai", "openai"]


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    api_key: str
    model: str
    endpoint: Optional[str] = None
    api_version: Optional[str] = None


def load_llm_config(*, purpose: str = "general") -> Optional[LLMConfig]:
    """
    Central place to configure LLM usage.

    Supported env:
    - Azure OpenAI:
        AZURE_OPENAI_ENDPOINT
        AZURE_OPENAI_API_KEY
        AZURE_OPENAI_API_VERSION (optional)
        AZURE_OPENAI_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT_NAME
    - OpenAI:
        OPENAI_API_KEY
        OPENAI_MODEL (optional)

    `purpose` allows future per-purpose overrides (router vs nl2sql), but currently
    reads the same env vars.
    """
    _ = purpose  # reserved for future override map

    az_endpoint = (os.environ.get("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/")
    az_key = (os.environ.get("AZURE_OPENAI_API_KEY") or "").strip()
    az_deployment = (
        (os.environ.get("AZURE_OPENAI_DEPLOYMENT") or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME") or "").strip()
    )
    az_version = (os.environ.get("AZURE_OPENAI_API_VERSION") or "").strip() or "2024-02-01"
    if az_endpoint and az_key and az_deployment:
        return LLMConfig(
            provider="azure_openai",
            api_key=az_key,
            endpoint=az_endpoint,
            api_version=az_version,
            model=az_deployment,
        )

    oai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    oai_model = (os.environ.get("OPENAI_MODEL") or "").strip() or "gpt-4o-mini"
    if oai_key:
        return LLMConfig(provider="openai", api_key=oai_key, model=oai_model)

    return None


def is_llm_enabled(*, purpose: str = "general") -> bool:
    return load_llm_config(purpose=purpose) is not None

