"""Model registry — resolves a provider/model string to a LangChain BaseChatModel.

All provider-specific imports are isolated here. Every other module uses only
BaseChatModel from langchain_core.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models import BaseChatModel


# Path to config file relative to this file
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict[str, Any]:
    """Load models/config.yaml and return the parsed dict."""
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _infer_provider(model_name: str) -> str:
    """Infer provider from model name when no prefix is given."""
    name = model_name.lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith("gpt"):
        return "openai"
    if name.startswith("gemini"):
        return "google"
    if name.startswith("mistral") or name.startswith("mixtral"):
        return "mistral"
    return "ollama"


def get_model(model_string: str | None = None) -> BaseChatModel:
    """Resolve a provider/model string to a LangChain BaseChatModel instance.

    Resolution priority:
    1. model_string argument
    2. MODEL environment variable
    3. models/config.yaml active.provider + active.model
    """
    config = _load_config()
    providers = config.get("providers", {})

    # Determine source and model string
    source = "models/config.yaml"
    if model_string is not None:
        source = "argument"
    elif os.environ.get("MODEL"):
        model_string = os.environ["MODEL"]
        source = "MODEL env var"
    else:
        active = config.get("active", {})
        provider = active.get("provider", "gemini")
        model = active.get("model", "gemini-2.0-flash")
        model_string = f"{provider}/{model}"
        source = "models/config.yaml"

    # Parse provider and model
    if "/" in model_string:
        provider_key, model_name = model_string.split("/", 1)
    else:
        # Auto-infer provider
        model_name = model_string
        inferred = _infer_provider(model_string)
        # Map inferred to canonical key
        provider_map = {
            "anthropic": "claude",
            "google": "gemini",
            "openai": "openai",
            "mistral": "mistral",
            "ollama": "ollama",
        }
        provider_key = provider_map.get(inferred, inferred)

    # Normalize provider key
    provider_aliases = {
        "google": "gemini",
        "anthropic": "claude",
        "openai_compat": "openai-compat",
    }
    provider_key = provider_aliases.get(provider_key.lower(), provider_key.lower())

    if provider_key not in providers:
        raise ValueError(
            f"Unknown provider '{provider_key}'. "
            f"Supported: {', '.join(providers.keys())}"
        )

    provider_cfg = providers[provider_key]
    env_var = provider_cfg.get("env_var")
    install_pkg = provider_cfg.get("install", "")

    # Check required env var
    if env_var and not os.environ.get(env_var):
        raise ValueError(
            f"Provider '{provider_key}' requires {env_var} env var. "
            f"Set it in .env"
        )

    # Build the model instance
    match provider_key:
        case "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError:
                raise ImportError(
                    f"Provider 'gemini' requires langchain-google-genai. "
                    f"Run: pip install langchain-google-genai"
                )
            return ChatGoogleGenerativeAI(model=model_name)

        case "claude":
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError:
                raise ImportError(
                    f"Provider 'claude' requires langchain-anthropic. "
                    f"Run: pip install langchain-anthropic"
                )
            return ChatAnthropic(model=model_name)

        case "openai":
            try:
                from langchain_openai import ChatOpenAI
            except ImportError:
                raise ImportError(
                    f"Provider 'openai' requires langchain-openai. "
                    f"Run: pip install langchain-openai"
                )
            return ChatOpenAI(model=model_name)

        case "openai-compat":
            try:
                from langchain_openai import ChatOpenAI
            except ImportError:
                raise ImportError(
                    "Provider 'openai-compat' requires langchain-openai. "
                    "Run: pip install langchain-openai"
                )
            base_url_env = provider_cfg.get("base_url_env", "OPENAI_COMPAT_BASE_URL")
            base_url = os.environ.get(base_url_env, "")
            api_key = os.environ.get(env_var, "")
            if not base_url:
                raise ValueError(
                    f"Provider 'openai-compat' requires {base_url_env} env var. "
                    "Set it in .env"
                )
            return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url)

        case "ollama":
            try:
                from langchain_ollama import ChatOllama
            except ImportError:
                raise ImportError(
                    f"Provider 'ollama' requires langchain-ollama. "
                    f"Run: pip install langchain-ollama"
                )
            return ChatOllama(model=model_name)

        case "mistral":
            try:
                from langchain_mistralai import ChatMistralAI
            except ImportError:
                raise ImportError(
                    f"Provider 'mistral' requires langchain-mistralai. "
                    f"Run: pip install langchain-mistralai"
                )
            return ChatMistralAI(model=model_name)

        case _:
            raise ValueError(f"Unsupported provider: '{provider_key}'")


def get_model_info(model_string: str | None = None) -> dict[str, str]:
    """Return info dict with provider, model, and source of model config."""
    config = _load_config()

    source = "models/config.yaml"
    if model_string is not None:
        source = "argument"
    elif os.environ.get("MODEL"):
        model_string = os.environ["MODEL"]
        source = "MODEL env var"
    else:
        active = config.get("active", {})
        provider = active.get("provider", "gemini")
        model = active.get("model", "gemini-2.0-flash")
        model_string = f"{provider}/{model}"
        source = "models/config.yaml"

    if "/" in model_string:
        provider_key, model_name = model_string.split("/", 1)
    else:
        model_name = model_string
        provider_key = _infer_provider(model_string)

    return {"provider": provider_key, "model": model_name, "source": source}


def list_supported_providers() -> dict[str, Any]:
    """Return the full providers dict from models/config.yaml."""
    config = _load_config()
    return config.get("providers", {})
