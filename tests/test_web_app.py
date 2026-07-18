"""Tests for web/app.py - React SPA routes."""
from __future__ import annotations


class TestWebApp:
    def test_index_html_exists(self):
        """Test that the React SPA template is non-empty."""
        from pulse.web.app import INDEX_HTML
        assert len(INDEX_HTML) > 100
        assert "Pulse Agent" in INDEX_HTML
        assert "React" in INDEX_HTML

    def test_create_web_app_callable(self):
        """Test that create_web_app is a callable."""
        from pulse.web.app import create_web_app
        assert callable(create_web_app)
