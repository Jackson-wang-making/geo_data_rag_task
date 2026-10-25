"""Embedding clients: local sentence-transformers bge-m3 (default) and Ollama (optional)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
import requests


class EmbedError(RuntimeError):
    """Actionable embedding failure. `code` is stable for the UI and evidence JSON."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class EmbeddingClient(Protocol):
    model_id: str
    dimension: int

    def health(self) -> None: ...

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class OllamaEmbeddingClient:
    """POST /api/embed against an Ollama server (Docker container recommended)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int = 1024,
        batch_size: int | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model_id = model or os.environ.get("EMBEDDING_MODEL", "bge-m3")
        self.dimension = dimension
        self.batch_size = int(batch_size or os.environ.get("EMBEDDING_BATCH_SIZE", 8))
        self.timeout = float(timeout or os.environ.get("EMBEDDING_TIMEOUT", 120))

    def health(self) -> None:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
        except requests.RequestException as exc:
            raise EmbedError(
                "EMBED_UNAVAILABLE",
                f"无法连接 Ollama（{self.base_url}）。请启动 Docker Desktop，并确认 embedding 容器已运行："
                f"`docker start trendee-ollama`。原始错误：{exc}",
            ) from exc
        if resp.status_code != 200:
            raise EmbedError("EMBED_UNAVAILABLE", f"Ollama 返回 HTTP {resp.status_code}，请检查服务状态。")
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(name.split(":")[0] == self.model_id.split(":")[0] for name in models):
            raise EmbedError(
                "EMBED_MODEL_MISSING",
                f"Ollama 未安装 `{self.model_id}`。请运行 `docker exec -it trendee-ollama ollama pull {self.model_id}`。",
            )

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            try:
                resp = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model_id, "input": batch},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise EmbedError(
                    "EMBED_UNAVAILABLE",
                    f"调用 Ollama embedding 失败（{self.base_url}）。请确认服务已启动。原始错误：{exc}",
                ) from exc
            if resp.status_code != 200:
                raise EmbedError(
                    "EMBED_UNAVAILABLE",
                    f"Ollama embedding 返回 HTTP {resp.status_code}，请检查服务日志。",
                )
            batch_vectors = resp.json().get("embeddings")
            if not isinstance(batch_vectors, list) or len(batch_vectors) != len(batch):
                raise EmbedError("EMBED_BAD_RESPONSE", "Ollama 返回的 embedding 数量与输入不一致。")
            vectors.extend(batch_vectors)

        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.dimension:
            raise EmbedError(
                "EMBED_BAD_RESPONSE",
                f"Embedding 维度异常：期望 {self.dimension}，实际 {matrix.shape}。",
            )
        if not np.isfinite(matrix).all():
            raise EmbedError("EMBED_BAD_RESPONSE", "Embedding 包含 NaN 或无穷值。")

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if (norms == 0).any():
            raise EmbedError("EMBED_BAD_RESPONSE", "Embedding 包含零向量。")
        return matrix / norms


class SentenceTransformerEmbeddingClient:
    """Local HuggingFace/ModelScope bge-m3 client (the default path).

    It produces the same 1024-dimensional, L2-normalized vectors as the Ollama
    client. The model directory is expected to contain a sentence-transformers
    layout (config.json, modules.json, tokenizer files, and pytorch_model.bin).
    """

    def __init__(
        self,
        model_path: str | None = None,
        model: str | None = None,
        dimension: int = 1024,
        batch_size: int | None = None,
        device: str | None = None,
    ):
        project_dir = Path(__file__).resolve().parents[1]
        raw_path = model_path or os.environ.get("EMBEDDING_MODEL_PATH")
        if raw_path:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                # A relative EMBEDDING_MODEL_PATH is relative to the project,
                # not to whatever directory the process happens to start in.
                path = project_dir / path
        else:
            path = project_dir / "data" / "bge-m3"
        self.model_path = path
        self.model_id = model or os.environ.get("EMBEDDING_MODEL", "bge-m3")
        self.dimension = int(dimension)
        self.batch_size = int(batch_size or os.environ.get("EMBEDDING_BATCH_SIZE", 8))
        self.device = device or os.environ.get("EMBEDDING_DEVICE", "cpu")
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.model_path.is_dir():
            raise EmbedError(
                "EMBED_MODEL_MISSING",
                f"本地 embedding 目录不存在：{self.model_path}。请下载 bge-m3 到该目录，"
                "或设置 EMBEDDING_MODEL_PATH 指向已有模型目录。",
            )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbedError(
                "EMBED_UNAVAILABLE",
                "未安装 sentence-transformers。请运行 `.venv/Scripts/python.exe -m pip install -r requirements.txt`。",
            ) from exc
        except Exception as exc:
            raise EmbedError(
                "EMBED_UNAVAILABLE",
                f"加载 sentence-transformers / torch 失败：{exc}",
            ) from exc
        try:
            model = SentenceTransformer(str(self.model_path), device=self.device)
        except Exception as exc:
            raise EmbedError(
                "EMBED_UNAVAILABLE",
                f"本地 bge-m3 加载失败（{self.model_path}）。请检查模型文件是否完整；原始错误：{exc}",
            ) from exc
        dimension_getter = getattr(model, "get_embedding_dimension", None)
        actual = dimension_getter() if dimension_getter else model.get_sentence_embedding_dimension()
        if actual != self.dimension:
            raise EmbedError(
                "EMBED_BAD_RESPONSE",
                f"本地 embedding 维度异常：期望 {self.dimension}，实际 {actual}。",
            )
        self._model = model
        return model

    def health(self) -> None:
        if not self.model_path.is_dir():
            raise EmbedError(
                "EMBED_MODEL_MISSING",
                f"本地 embedding 目录不存在：{self.model_path}。",
            )
        self._load()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        model = self._load()
        try:
            vectors = model.encode(
                list(texts),
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbedError("EMBED_BAD_RESPONSE", f"本地 embedding 推理失败：{exc}") from exc
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[0] != len(texts) or matrix.shape[1] != self.dimension:
            raise EmbedError(
                "EMBED_BAD_RESPONSE",
                f"Embedding 维度异常：期望 ({len(texts)}, {self.dimension})，实际 {matrix.shape}。",
            )
        if not np.isfinite(matrix).all():
            raise EmbedError("EMBED_BAD_RESPONSE", "Embedding 包含 NaN 或无穷值。")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if (norms == 0).any():
            raise EmbedError("EMBED_BAD_RESPONSE", "Embedding 包含零向量。")
        return matrix / norms


def build_embedding_client(
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    model_path: str | None = None,
    device: str | None = None,
) -> EmbeddingClient:
    """Build the embedding client selected by EMBEDDING_PROVIDER.

    `local` (sentence-transformers bge-m3) is the default and needs no Docker;
    `ollama` is an explicit optional path. It never silently substitutes a
    different model.
    """
    selected = (provider or os.environ.get("EMBEDDING_PROVIDER", "local")).strip().lower()
    if selected == "ollama":
        return OllamaEmbeddingClient(base_url=base_url, model=model)
    if selected in ("local", "sentence_transformers", "sentence-transformers"):
        return SentenceTransformerEmbeddingClient(model_path=model_path, model=model, device=device)
    raise EmbedError(
        "EMBED_PROVIDER_UNSUPPORTED",
        f"EMBEDDING_PROVIDER={selected} 不支持；请使用 local 或 ollama。",
    )
