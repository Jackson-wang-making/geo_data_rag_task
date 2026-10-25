"""Provider adapter error mapping; messages must never expose the API key."""

import pytest

from trendee_rag.llm import LLMError, OpenAICompatibleClient

FAKE_KEY = "test-secret-should-not-leak"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def client():
    return OpenAICompatibleClient(
        base_url="https://example.invalid/v1", api_key=FAKE_KEY, model="fake", timeout=1
    )


def test_success_returns_content(monkeypatch):
    monkeypatch.setattr(
        "trendee_rag.llm.requests.post",
        lambda *args, **kwargs: FakeResponse(
            payload={
                "model": "fake",
                "choices": [{"message": {"content": "正文"}, "finish_reason": "stop"}],
            }
        ),
    )
    response = client().complete([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=10)
    assert response.text == "正文"
    assert response.finish_reason == "stop"


def test_reasoning_exhaustion_maps_to_truncated(monkeypatch):
    monkeypatch.setattr(
        "trendee_rag.llm.requests.post",
        lambda *args, **kwargs: FakeResponse(
            payload={
                "model": "fake",
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            }
        ),
    )
    with pytest.raises(LLMError) as exc:
        client().complete([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=10)
    assert exc.value.code == "LLM_TRUNCATED"
    assert FAKE_KEY not in str(exc.value)


def test_auth_failure_does_not_leak_key(monkeypatch):
    monkeypatch.setattr(
        "trendee_rag.llm.requests.post",
        lambda *args, **kwargs: FakeResponse(status_code=401),
    )
    with pytest.raises(LLMError) as exc:
        client().complete([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=10)
    assert exc.value.code == "LLM_UNAVAILABLE"
    assert FAKE_KEY not in str(exc.value)
