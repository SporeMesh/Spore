"""Tests for LLM client retry behavior."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from spore.llm import LLMClient, LLMConfig


def make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            model="test-model",
        )
    )


def test_post_with_retry_retries_transient_request_errors(monkeypatch):
    client = make_client()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    }
    client.session.post = Mock(
        side_effect=[
            requests.exceptions.ConnectionError("boom"),
            response,
        ]
    )
    monkeypatch.setattr("spore.llm.time.sleep", lambda _seconds: None)

    result = client.chat("system", "user")

    assert result == "ok"
    assert client.session.post.call_count == 2


def test_post_with_retry_raises_after_max_attempts(monkeypatch):
    client = make_client()
    client.session.post = Mock(side_effect=requests.exceptions.ConnectionError("boom"))
    monkeypatch.setattr("spore.llm.time.sleep", lambda _seconds: None)

    with pytest.raises(requests.exceptions.ConnectionError):
        client.chat("system", "user")
