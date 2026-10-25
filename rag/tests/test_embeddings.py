"""Embedding provider selection and the default local bge-m3 contract."""

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from trendee_rag.embeddings import (
    EmbedError,
    OllamaEmbeddingClient,
    SentenceTransformerEmbeddingClient,
    build_embedding_client,
)


class FakeModel:
    def __init__(self, path, device):
        self.path = path
        self.device = device

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, **kwargs):
        return np.asarray([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]][: len(texts)], dtype=np.float32)


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return module


def test_factory_defaults_to_local(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    client = build_embedding_client()
    assert isinstance(client, SentenceTransformerEmbeddingClient)


def test_factory_builds_explicit_ollama_provider():
    client = build_embedding_client(provider="ollama", base_url="http://127.0.0.1:9")
    assert isinstance(client, OllamaEmbeddingClient)


def test_factory_builds_local_provider(fake_sentence_transformers, tmp_path):
    fake_sentence_transformers.SentenceTransformer = type(
        "WideModel", (FakeModel,), {"get_sentence_embedding_dimension": lambda self: 1024}
    )
    client = build_embedding_client(provider="local", model_path=str(tmp_path))
    assert isinstance(client, SentenceTransformerEmbeddingClient)
    client.health()

    relative = SentenceTransformerEmbeddingClient(model_path="data/bge-m3")
    assert relative.model_path == Path(__file__).resolve().parents[1] / "data" / "bge-m3"


def test_factory_rejects_unknown_provider():
    with pytest.raises(EmbedError) as exc:
        build_embedding_client(provider="openai")
    assert exc.value.code == "EMBED_PROVIDER_UNSUPPORTED"


def test_local_encode_normalizes(fake_sentence_transformers, tmp_path):
    client = SentenceTransformerEmbeddingClient(
        model_path=str(tmp_path), dimension=3, batch_size=2
    )
    vectors = client.encode(["a", "b"])

    assert vectors.shape == (2, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_local_missing_model_directory_fails_closed(tmp_path):
    missing = tmp_path / "missing"
    client = SentenceTransformerEmbeddingClient(model_path=str(missing))

    with pytest.raises(EmbedError) as exc:
        client.health()
    assert exc.value.code == "EMBED_MODEL_MISSING"


def test_local_dimension_mismatch_fails_closed(fake_sentence_transformers, tmp_path):
    client = SentenceTransformerEmbeddingClient(model_path=str(tmp_path), dimension=1024)

    with pytest.raises(EmbedError) as exc:
        client.encode(["a"])
    assert exc.value.code == "EMBED_BAD_RESPONSE"
