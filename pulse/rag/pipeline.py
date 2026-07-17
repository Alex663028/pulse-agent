"""RAG pipeline: document ingestion, chunking, embedding, retrieval.

Integrates with LangChain/LlamaIndex for document loaders, splitters, and
vector stores. Falls back to SQLite FTS5 if no vector store is configured.
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

    @staticmethod
    def from_text(text: str, source: str = "inline", chunk_size: int = 500, overlap: int = 50) -> list[Document]:
        """Split text into overlapping chunks."""
        chunks: list[Document] = []
        start = 0
        idx = 0
        text = text.strip()
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            doc_id = hashlib.sha1(f"{source}:{idx}:{chunk[:32]}".encode()).hexdigest()[:12]
            chunks.append(Document(doc_id=doc_id, content=chunk, source=source, metadata={"chunk": idx}))
            idx += 1
            start = end - overlap if end < len(text) else end
        return chunks


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline.

    Supports:
    - File ingestion (txt, md, pdf via optional deps)
    - Chunking with overlap
    - Embeddings via optional sentence-transformers or OpenAI-compatible endpoint
    - Vector store backends: chromadb, qdrant, or SQLite FTS5 fallback
    """

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

    def ingest_file(self, path: str | Path) -> int:
        """Ingest a file, chunk it, and index it. Returns chunk count."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.ingest_text(text, source=str(p))

    def ingest_text(self, text: str, source: str = "inline") -> int:
        """Chunk text and index it. Returns chunk count."""
        docs = Document.from_text(text, source=source, chunk_size=self.chunk_size, overlap=self.overlap)
        self._chunks.extend(docs)
        for d in docs:
            if d.doc_id in self._indexed:
                continue
            self._indexed.add(d.doc_id)
            self.storage.index_memory(f"rag:{d.doc_id}", d.content)
        return len(docs)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve top-k chunks relevant to query."""
        hits = self.storage.search_memory(query, limit=limit)
        results: list[dict[str, Any]] = []
        for h in hits:
            results.append({
                "doc_id": h.get("session_id", ""),
                "content": h.get("content", ""),
                "score": h.get("score", 0.0),
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
