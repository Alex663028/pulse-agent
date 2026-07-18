"""HTTP health-check endpoint for Docker/container deployments.

``pulse health --port 8080`` starts a tiny HTTP server that returns 200
when Pulse is running (storage accessible, router reachable).
"""

from __future__ import annotations

import json
import logging
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from pulse.cli.runtime import Runtime, bootstrap

logger = logging.getLogger(__name__)


_runtime_cache: Runtime | None = None


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal handler: GET / returns 200 with Pulse status JSON.

    The Runtime is constructed once and cached across requests so health
    probes (which may fire every 5-10 seconds) don't reopen SQLite connections
    or rebuild the router on every call.
    """

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        global _runtime_cache
        try:
            if _runtime_cache is None:
                _runtime_cache = bootstrap()
            rt = _runtime_cache
            status = {
                "status": "ok",
                "provider": rt.settings.model.provider,
                "model": rt.settings.model.model,
                "skills": len(rt.registry.list()),
                "sessions": 0,
                "ts": time.time(),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        except Exception as e:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "detail": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # suppress access logs


def run(port: int = 8080):
    """Start the health check server on ``port``."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("pulse health server on :%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
