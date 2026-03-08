"""Tests for models/registry.py — model resolution, provider routing, auto-inference."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clear_model_env(monkeypatch):
    """Ensure MODEL env var does not interfere with tests."""
    monkeypatch.delenv("MODEL", raising=False)


def _mock_provider(env_var: str | None, monkeypatch):
    """Set required env var for provider tests."""
    if env_var:
        monkeypatch.setenv(env_var, "test-key-value")


def test_get_model_gemini(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_google_genai": MagicMock(ChatGoogleGenerativeAI=mock_cls)}):
        from models.registry import get_model
        result = get_model("gemini/gemini-2.0-flash")
        mock_cls.assert_called_once_with(model="gemini-2.0-flash")


def test_get_model_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_anthropic": MagicMock(ChatAnthropic=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        result = registry.get_model("claude/claude-opus-4-5")
        mock_cls.assert_called_once_with(model="claude-opus-4-5")


def test_get_model_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        result = registry.get_model("openai/gpt-4o")
        mock_cls.assert_called_once_with(model="gpt-4o")


def test_get_model_ollama(monkeypatch):
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_ollama": MagicMock(ChatOllama=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        result = registry.get_model("ollama/llama3.1")
        mock_cls.assert_called_once_with(model="llama3.1")


def test_get_model_auto_infer_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        registry.get_model("gpt-4o-mini")
        mock_cls.assert_called_once_with(model="gpt-4o-mini")


def test_get_model_auto_infer_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_anthropic": MagicMock(ChatAnthropic=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        registry.get_model("claude-3-5-sonnet")
        mock_cls.assert_called_once_with(model="claude-3-5-sonnet")


def test_get_model_auto_infer_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_google_genai": MagicMock(ChatGoogleGenerativeAI=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        registry.get_model("gemini-1.5-pro")
        mock_cls.assert_called_once_with(model="gemini-1.5-pro")


def test_get_model_unknown_raises_valueerror(monkeypatch):
    from models import registry
    import importlib
    importlib.reload(registry)
    # Use an explicit unknown/provider prefix — "unknown" is not in the providers registry
    with pytest.raises(ValueError, match="[Uu]nknown|[Uu]nsupported"):
        registry.get_model("unknownprovider/some-model")


def test_missing_api_key_raises_valueerror(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from models import registry
    import importlib
    importlib.reload(registry)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        registry.get_model("gemini/gemini-2.0-flash")


def test_get_model_no_arg_reads_config(monkeypatch):
    # Active config is openai-compat, so set those env vars
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "fake-key")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://fake.api.test/v1")
    mock_cls = MagicMock()
    with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
        from models import registry
        import importlib
        importlib.reload(registry)
        registry.get_model()
        mock_cls.assert_called_once()


def test_get_model_info_returns_required_keys():
    from models.registry import get_model_info
    info = get_model_info("gemini/gemini-2.0-flash")
    assert "provider" in info
    assert "model" in info
    assert "source" in info
    assert info["source"] == "argument"


def test_list_supported_providers_returns_five():
    from models.registry import list_supported_providers
    providers = list_supported_providers()
    assert isinstance(providers, dict)
    assert len(providers) >= 5
    assert "gemini" in providers
    assert "claude" in providers
    assert "openai" in providers
    assert "ollama" in providers
    assert "mistral" in providers
