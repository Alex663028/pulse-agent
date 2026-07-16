"""Tests for RAG pipeline and tracing extensions."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.observability.tracing import LangFuseTracer, LangSmithTracer, Trace, TraceStore
from pulse.rag.pipeline import Document, RAGPipeline
from pulse.rag.vector import SQLiteVectorStore
from pulse.storage.engine import Storage


class TestDocument:
    def test_from_text_chunks(self):
        text = "hello world " * 100
        docs = Document.from_text(text, source="test", chunk_size=20, overlap=5)
        assert len(docs) > 1
        assert all(d.source == "test" for d in docs)
        assert all(len(d.content) <= 20 for d in docs)

    def test_from_text_empty(self):
        docs = Document.from_text("", source="x")
        assert docs == []


class TestRAGPipeline:
    def test_ingest_file(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("hello world " * 50)
        storage = MagicMock()
        memory = MagicMock()
        rag = RAGPipeline(storage, memory, chunk_size=20, overlap=5)
        count = rag.ingest_file(p)
        assert count > 0

    def test_ingest_text(self, tmp_path):
        storage = MagicMock()
        memory = MagicMock()
        rag = RAGPipeline(storage, memory, chunk_size=20, overlap=5)
        count = rag.ingest_text("hello world " * 50, source="inline")
        assert count > 0

    def test_search_delegates_to_storage(self, tmp_path):
        storage = MagicMock()
        storage.search_memory.return_value = [
            {"session_id": "rag:abc:1", "content": "hello", "score": 1.0}
        ]
        memory = MagicMock()
        rag = RAGPipeline(storage, memory)
        hits = rag.search("hello", limit=1)
        assert hits[0]["doc_id"] == "rag:abc:1"
        assert hits[0]["content"] == "hello"

    def test_build_context_empty(self, tmp_path):
        storage = MagicMock()
        storage.search_memory.return_value = []
        memory = MagicMock()
        rag = RAGPipeline(storage, memory)
        ctx = rag.build_context("nothing", limit=3)
        assert ctx == ""

    def test_build_context_returns_chunks(self, tmp_path):
        storage = MagicMock()
        storage.search_memory.return_value = [
            {"session_id": "rag:1:1", "content": "chunk one", "score": 0.9},
            {"session_id": "rag:2:1", "content": "chunk two", "score": 0.8},
        ]
        memory = MagicMock()
        rag = RAGPipeline(storage, memory)
        ctx = rag.build_context("query", limit=2)
        assert "[1] chunk one" in ctx
        assert "[2] chunk two" in ctx


class TestSQLiteVectorStore:
    def test_upsert_and_search(self, tmp_path):
        db = tmp_path / "pulse.db"
        storage = Storage(db)
        store = SQLiteVectorStore(storage)
        store.upsert("doc1", "hello world")
        hits = store.search("hello", limit=1)
        assert len(hits) == 1
        assert hits[0].doc_id == "doc1"


class TestTraceStore:
    def test_record_and_get_trace(self):
        ts = TraceStore(max_traces=10)
        t = Trace(trace_id="t1", span_id="s1", name="test", kind="span", data={"x": 1})
        ts.record(t)
        assert ts.get_trace("t1") == [t]

    def test_ring_buffer(self):
        ts = TraceStore(max_traces=2)
        for i in range(3):
            ts.record(Trace(trace_id=f"t{i}", span_id=f"s{i}", name=f"n{i}"))
        assert len(ts._traces) == 2

    def test_export_json(self):
        ts = TraceStore()
        ts.record(Trace(trace_id="t1", span_id="s1", name="n", kind="event"))
        out = json.loads(ts.export_json())
        assert len(out) == 1
        assert out[0]["trace_id"] == "t1"


class TestLangSmithTracer:
    def test_disabled_without_key(self):
        tracer = LangSmithTracer(api_key="")
        tracer.export([])  # should not raise

    def test_enabled_calls_endpoint(self):
        tracer = LangSmithTracer(api_key="k")
        with patch("pulse.observability.tracing.urllib.request.urlopen") as mock_urlopen:
            tracer.export([Trace(trace_id="t1", span_id="s1", name="n")])
            assert mock_urlopen.called


class TestLangFuseTracer:
    def test_disabled_without_keys(self):
        tracer = LangFuseTracer(public_key="", secret_key="")
        tracer.export([])  # should not raise

    def test_enabled_calls_endpoint(self):
        tracer = LangFuseTracer(public_key="p", secret_key="s")
        with patch("pulse.observability.tracing.urllib.request.urlopen") as mock_urlopen:
            tracer.export([Trace(trace_id="t1", span_id="s1", name="n")])
            assert mock_urlopen.called


class TestRuntimeExtensions:
    def test_apply_extensions_rag_disabled(self):
        rt = MagicMock()
        rt.settings.rag_enabled = False
        rt.settings.trace_enabled = False
        from pulse.cli.runtime_ext import apply_extensions
        apply_extensions(rt)
        assert rt.ext.rag is None
        assert rt.ext.trace_store is None

    def test_apply_extensions_rag_enabled(self):
        rt = MagicMock()
        rt.settings.rag_enabled = True
        rt.settings.rag_vector_backend = "sqlite"
        rt.settings.rag_chunk_size = 100
        rt.settings.rag_overlap = 10
        rt.settings.trace_enabled = False
        from pulse.cli.runtime_ext import apply_extensions
        apply_extensions(rt)
        assert rt.ext.rag is not None

    def test_apply_extensions_trace_enabled(self):
        rt = MagicMock()
        rt.settings.rag_enabled = False
        rt.settings.trace_enabled = True
        rt.settings.langsmith_api_key = "k"
        rt.settings.langfuse_public_key = ""
        rt.settings.langfuse_secret_key = ""
        from pulse.cli.runtime_ext import apply_extensions
        apply_extensions(rt)
        assert rt.ext.trace_store is not None
        assert rt.ext.langsmith is not None
        assert rt.ext.langfuse is None
