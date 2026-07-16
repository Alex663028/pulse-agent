"""Runtime extensions: optional RAG + trace/LangSmith/LangFuse wiring."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from pulse.config.settings import Settings
from pulse.memory.store import MemoryStore
from pulse.observability.tracing import LangFuseTracer, LangSmithTracer, TraceStore
from pulse.rag.pipeline import RAGPipeline
from pulse.storage.engine import Storage

logger = logging.getLogger(__name__)


@dataclass
class RuntimeExtensions:
    rag: Optional[RAGPipeline] = None
    trace_store: Optional[TraceStore] = None
    langsmith: Optional[LangSmithTracer] = None
    langfuse: Optional[LangFuseTracer] = None


def apply_extensions(rt) -> None:
    """Attach optional extensions to an existing Runtime if enabled in settings."""
    settings: Settings = rt.settings
    ext = RuntimeExtensions()

    if getattr(settings, "rag_enabled", False):
        try:
            ext.rag = RAGPipeline(
                storage=rt.storage,
                memory=rt.memory,
                vector_backend=getattr(settings, "rag_vector_backend", "sqlite"),
                chunk_size=getattr(settings, "rag_chunk_size", 500),
                overlap=getattr(settings, "rag_overlap", 50),
            )
            logger.info("[extensions] RAG pipeline enabled")
        except Exception as e:
            logger.warning("[extensions] RAG init failed: %s", e)

    if getattr(settings, "trace_enabled", False):
        ext.trace_store = TraceStore(max_traces=5000)
        if getattr(settings, "langsmith_api_key", ""):
            ext.langsmith = LangSmithTracer(api_key=settings.langsmith_api_key)
        if getattr(settings, "langfuse_public_key", "") and getattr(settings, "langfuse_secret_key", ""):
            ext.langfuse = LangFuseTracer(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
            )
        logger.info("[extensions] tracing enabled")

    rt.ext = ext
