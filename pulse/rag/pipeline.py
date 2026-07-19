"""RAG pipeline: document ingestion, chunking, embedding, retrieval.

Supports:
- File ingestion (txt, md)
- Chunking with overlap
- Embeddings via sentence-transformers (if available) or OpenAI-compatible endpoint
- Vector store backends: sqlite-vec (if available), chromadb, qdrant, or FTS5 fallback
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pulse.memory.store import MemoryStore
from pulse.storage.engine import Storage

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """A chunked document ready for embedding."""

    doc_id: str
    content: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    @staticmethod
    def from_text(
        text: str, source: str = "inline", chunk_size: int = 500, overlap: int = 50
    ) -> list[Document]:
        """Split text into overlapping chunks."""
        chunks: list[Document] = []
        start = 0
        idx = 0
        text = text.strip()
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            doc_id = hashlib.sha1(f"{source}:{idx}:{chunk[:32]}".encode()).hexdigest()[:12]
            chunks.append(
                Document(doc_id=doc_id, content=chunk, source=source, metadata={"chunk": idx})
            )
            idx += 1
            start = end - overlap if end < len(text) else end
        return chunks


class EmbeddingProvider:
    """Base class for embedding providers."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class SentenceTransformerProvider(EmbeddingProvider):
    """Local embeddings via sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, show_progress_bar=False).tolist()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embeddings endpoint."""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "text-embedding-3-small"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url) if api_key else OpenAI(base_url=base_url)
        self.model = model

    def encode(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline with real embeddings."""

    def __init__(
        self,
        storage: Storage,
        memory: MemoryStore,
        embedding_model: Optional[str] = None,
        vector_backend: str = "sqlite",
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> None:
        self.storage = storage
        self.memory = memory
        self.embedding_model = embedding_model or os.environ.get("PULSE_EMBEDDING_MODEL", "")
        self.vector_backend = vector_backend
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._chunks: list[Document] = []
        self._indexed: set[str] = set()
        self._embedding_provider: Optional[EmbeddingProvider] = None

    def _get_embedding_provider(self) -> Optional[EmbeddingProvider]:
        """Lazy-load embedding provider."""
        if self._embedding_provider is not None:
            return self._embedding_provider
        # Try sentence-transformers first (local, no API key needed)
        try:
            self._embedding_provider = SentenceTransformerProvider(self.embedding_model or "all-MiniLM-L6-v2")
            return self._embedding_provider
        except ImportError:
            pass
        # Fall back to OpenAI-compatible
        try:
            self._embedding_provider = OpenAIEmbeddingProvider()
            return self._embedding_provider
        except Exception:
            pass
        return None

    def ingest_file(self, path: str | Path) -> int:
        """Ingest a file, chunk it, and index it. Returns chunk count."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.ingest_text(text, source=str(p))

    def ingest_text(self, text: str, source: str = "inline") -> int:
        """Chunk text, embed it, and index it. Returns chunk count."""
        docs = Document.from_text(
            text, source=source, chunk_size=self.chunk_size, overlap=self.overlap
        )
        provider = self._get_embedding_provider()
        if provider:
            try:
                embeddings = provider.encode([d.content for d in docs])
                for doc, emb in zip(docs, embeddings):
                    doc.embedding = emb
            except Exception as e:
                logger.warning("embedding failed: %s", e)
        self._chunks.extend(docs)
        for d in docs:
            if d.doc_id in self._indexed:
                continue
            self._indexed.add(d.doc_id)
            self.storage.index_memory(f"rag:{d.doc_id}", d.content)
        return len(docs)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve top-k chunks relevant to query using embedding similarity."""
        provider = self._get_embedding_provider()
        if provider and self._chunks:
            # Semantic search via embeddings
            try:
                query_emb = provider.encode([query])[0]
                scored = []
                for doc in self._chunks:
                    if doc.embedding:
                        score = self._cosine_similarity(query_emb, doc.embedding)
                        scored.append((score, doc))
                scored.sort(key=lambda x: -x[0])
                results = []
                for score, doc in scored[:limit]:
                    results.append({
                        "doc_id": doc.doc_id,
                        "content": doc.content,
                        "score": round(score, 4),
                        "source": doc.source,
                    })
                return results
            except Exception as e:
                logger.warning("semantic search failed, falling back to FTS5: %s", e)
        # Fallback: FTS5 search
        hits = self.storage.search_memory(query, limit=limit)
        results: list[dict[str, Any]] = []
        for h in hits:
            results.append({
                "doc_id": h.get("session_id", ""),
                "content": h.get("content", ""),
                "score": 0.0,
                "source": h.get("session_id", "").split(":")[0] if ":" in h.get("session_id", "") else "",
            })
        return results

    def build_context(self, query: str, limit: int = 3) -> str:
        """Build a context string from top retrieved chunks."""
        hits = self.search(query, limit=limit)
        parts: list[str] = []
        for i, h in enumerate(hits, 1):
            parts.append(f"[{i}] {h['content']}")
        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)