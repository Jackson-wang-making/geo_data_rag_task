"""Core package for the Trendee RAG brand-content writing system.

Modules are deliberately separated by responsibility:

- ``knowledge``: PDF parsing, chunking, indexing, and hybrid retrieval.
- ``embeddings``: local bge-m3 (default) and optional Ollama clients.
- ``llm``: OpenAI-compatible chat client (DeepSeek by default).
- ``writer``: prompt, structure contract, one repair attempt, status model.
- ``validation``: deterministic citation checks and entailment verifier.
- ``artifacts``: ``article.md`` / ``evidence.json`` writing.

The Streamlit entry point is ``app.py`` at the project root.
"""

__version__ = "0.1.0"
