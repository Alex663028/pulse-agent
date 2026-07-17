"""Vector store abstraction for RAG.

Backends:
- sqlite: built-in FTS5 fallback, no extra deps
- chromadb: optional chromadb package
- qdrant: optional qdrant-client package
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pulse.storage.engine import Storage

logger = logging.getLogger(__name__)


@dataclass
class Hit:
    doc_id: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class VectorStore:
    """Thin vector-store interface.

    Real embeddings are optional; without an embedding provider we fall back
    to SQLite FTS5 keyword search so RAG still works out-of-the-box.
    """

    def upsert(self, doc_id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        raise NotImplementedError


class SQLiteVectorStore(VectorStore):
    """FTS5-backed keyword vector store (no external deps)."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def upsert(self, doc_id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        self.storage.index_memory(f"rag:{doc_id}", text)

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        rows = self.storage.search_memory(query, limit=limit)
        return [
            Hit(
                doc_id=row.get("session_id", "").split(":", 1)[-1],
                content=row.get("content", ""),
                score=float(row.get("score", 0.0)),
                metadata={"source": row.get("session_id", "")},
            )
            for row in rows
        ]


class ChromaVectorStore(VectorStore):
    """Optional ChromaDB vector store."""

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def upsert(self, doc_id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        self._col.add(documents=[text], ids=[doc_id], metadatas=[metadata or {}])

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        try:
            res = self._col.query(query_texts=[query], n_results=limit)
        except Exception as e:
            logger.warning("chromadb query failed: %s", e)
            return []
        hits: list[Hit] = []
        docs = (res.get("documents") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, doc_id, dist in zip(docs, ids, dists):
            hits.append(Hit(doc_id=doc_id, content=doc, score=1.0 - float(dist)))
        return hits


class QdrantVectorStore(VectorStore):
    """Optional Qdrant vector store."""

    def __init__(self, client: Any, collection: str = "pulse-rag") -> None:
        self._client = client
        self._collection = collection

    def upsert(self, doc_id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        try:
            from qdrant_client.http import models  # type: ignore
            self._client.upsert(
                collection_name=self._collection,
                points=[
                    models.PointStruct(id=doc_id, payload={"text": text, **(metadata or {})}, vector=[0.0])
                ],
            )
        except Exception as e:
            logger.warning("qdrant upsert failed: %s", e)

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        try:
            res = self._client.search(collection_name=self._collection, query_vector=[0.0], limit=limit)
            return [Hit(doc_id=str(r.id), content=r.payload.get("text", ""), score=float(r.score or 0.0)) for r in res]
        except Exception as e:
            logger.warning("qdrant search failed: %s", e)
            return []
