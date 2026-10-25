"""Non-streaming chat-completion adapter. DeepSeek uses the OpenAI-compatible API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Protocol

import requests

DEFAULT_MODEL = "deepseek-flash"


class LLMError(RuntimeError):
    """Stable error code for the UI and evidence manifest. Never includes the API key."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class LLMResponse:
    text: str
    finish_reason: str
    model: str


class LLMClient(Protocol):
    model_id: str

    def complete(self, messages: List[dict], temperature: float, max_tokens: int) -> LLMResponse: ...


class OpenAICompatibleClient:
    provider = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model
        self.timeout = float(timeout or os.environ.get("LLM_TIMEOUT", 300))

    def complete(self, messages: List[dict], temperature: float, max_tokens: int) -> LLMResponse:
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_id,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(
                "LLM_UNAVAILABLE",
                f"无法连接 LLM 服务（{self.base_url}）。请检查网络与 .env 配置。",
            ) from exc

        if resp.status_code == 401:
            raise LLMError("LLM_UNAVAILABLE", "LLM 鉴权失败（401）。请检查 .env 中的 LLM_API_KEY。")
        if resp.status_code != 200:
            request_id = resp.headers.get("x-request-id", "")
            suffix = f"（request id: {request_id}）" if request_id else ""
            raise LLMError("LLM_UNAVAILABLE", f"LLM 返回 HTTP {resp.status_code}{suffix}。")

        try:
            choice = resp.json()["choices"][0]
            text = (choice["message"]["content"] or "").strip()
            finish_reason = choice.get("finish_reason") or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("LLM_BAD_RESPONSE", "LLM 返回结构不符合预期。") from exc
        if not text:
            if finish_reason == "length":
                raise LLMError(
                    "LLM_TRUNCATED",
                    "LLM 在输出上限内没有产生正文（reasoning 可能耗尽了 tokens）。"
                    "请提高 MAX_OUTPUT_TOKENS，或换用非 reasoning 模型。",
                )
            raise LLMError("LLM_BAD_RESPONSE", "LLM 返回空内容。")
        return LLMResponse(text=text, finish_reason=finish_reason, model=resp.json().get("model", self.model_id))


def build_llm_client() -> OpenAICompatibleClient:
    """Build the configured provider or fail closed with LLM_UNAVAILABLE."""
    provider = os.environ.get("LLM_PROVIDER", "openai_compatible").strip().lower()
    if provider != "openai_compatible":
        raise LLMError(
            "LLM_UNAVAILABLE",
            f"LLM_PROVIDER={provider} 尚未接入；请设置 LLM_PROVIDER=openai_compatible 并使用 DeepSeek。",
        )
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not base_url or not api_key:
        raise LLMError(
            "LLM_UNAVAILABLE",
            "未配置 LLM_BASE_URL 或 LLM_API_KEY。请复制 .env.example 为 .env 并填写 DeepSeek 配置。",
        )
    return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model)
