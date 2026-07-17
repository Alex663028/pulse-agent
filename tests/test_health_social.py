"""Tests for health check endpoint and social gateway webhook handling."""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch
from urllib.request import urlopen, HTTPError

import pytest

from pulse.cli import health


def _start_server():
    from http.server import HTTPServer

    server = HTTPServer(("127.0.0.1", 0), health.HealthHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    return server, port


def test_health_returns_200_and_status_json():
    """Health endpoint returns 200 with a JSON status body."""
    from pulse.cli import health
    orig_cache = health._runtime_cache
    health._runtime_cache = None
    try:
        mock_rt = MagicMock()
        mock_rt.settings.model.provider = "ollama"
        mock_rt.settings.model.model = "qwen2.5:7b"
        mock_rt.registry.list.return_value = ["skill_a", "skill_b"]
        health._runtime_cache = mock_rt

        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), health.HealthHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            resp = urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            body = json.loads(resp.read().decode())
            assert resp.getcode() == 200
            assert body["status"] == "ok"
            assert body["provider"] == "ollama"
            assert body["model"] == "qwen2.5:7b"
            assert body["skills"] == 2
        finally:
            server.shutdown()
            server.server_close()
    finally:
        health._runtime_cache = orig_cache


def test_health_404_for_unknown_path():
    """Health endpoint returns 404 for non-root paths."""
    from pulse.cli import health
    orig_cache = health._runtime_cache
    health._runtime_cache = None
    try:
        mock_rt = MagicMock()
        health._runtime_cache = mock_rt
        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), health.HealthHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with pytest.raises(HTTPError) as excinfo:
                urlopen(f"http://127.0.0.1:{port}/unknown", timeout=3)
            assert excinfo.value.code == 404
        finally:
            server.shutdown()
            server.server_close()
    finally:
        health._runtime_cache = orig_cache


def test_health_caches_runtime():
    """Health endpoint caches the Runtime across requests."""
    from pulse.cli import health
    orig_cache = health._runtime_cache
    health._runtime_cache = None
    try:
        mock_rt = MagicMock()
        mock_rt.settings.model.provider = "ollama"
        mock_rt.settings.model.model = "qwen2.5:7b"
        mock_rt.registry.list.return_value = []
        # Bootstrap should be called once (on first request)
        with patch.object(health, "bootstrap", return_value=mock_rt) as mock_boot:
            from http.server import HTTPServer
            server = HTTPServer(("127.0.0.1", 0), health.HealthHandler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
                urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
                urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
                # Bootstrap should be called exactly once
                assert mock_boot.call_count == 1
            finally:
                server.shutdown()
                server.server_close()
    finally:
        health._runtime_cache = orig_cache


def test_health_returns_503_on_error():
    """Health endpoint returns 503 when bootstrap raises."""
    from pulse.cli import health
    orig_cache = health._runtime_cache
    health._runtime_cache = None
    try:
        with patch.object(health, "bootstrap", side_effect=Exception("db fail")):
            from http.server import HTTPServer
            server = HTTPServer(("127.0.0.1", 0), health.HealthHandler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                with pytest.raises(HTTPError) as excinfo:
                    urlopen(f"http://127.0.0.1:{port}/", timeout=3)
                assert excinfo.value.code == 503
                body = json.loads(excinfo.value.read().decode())
                assert body["status"] == "error"
                assert "db fail" in body["detail"]
            finally:
                server.shutdown()
                server.server_close()
    finally:
        health._runtime_cache = orig_cache


# ──────────────────────────────────────────────────────────────────────
# social.py webhook tests
# ──────────────────────────────────────────────────────────────────────

def test_safe_webhook_text_strips_control_chars():
    """_safe_webhook_text strips non-printable control characters."""
    from pulse.gateways.social import _safe_webhook_text
    result = _safe_webhook_text("hello\x00world\x07foo")
    assert result == "helloworldfoo"


def test_safe_webhook_text_limits_length():
    """_safe_webhook_text enforces max_length."""
    from pulse.gateways.social import _safe_webhook_text
    result = _safe_webhook_text("a" * 10000)
    assert len(result) == 4096


def test_safe_webhook_text_empty_input():
    """_safe_webhook_text handles empty input."""
    from pulse.gateways.social import _safe_webhook_text
    assert _safe_webhook_text("") == ""


def test_safe_webhook_text_preserves_unicode():
    """_safe_webhook_text preserves normal unicode."""
    from pulse.gateways.social import _safe_webhook_text
    result = _safe_webhook_text("hello world 你好")
    assert result == "hello world 你好"


def test_social_gateway_audit_logger_exists():
    """SocialGateway should have an audit logger configured."""
    from pulse.gateways.social import _audit_webhook
    # Just verify function is callable
    assert callable(_audit_webhook)
