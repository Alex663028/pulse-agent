"""HTTP health-check endpoint for Docker/container deployments.

``pulse health --port 8080`` starts a tiny HTTP server that returns 200
when Pulse is running (storage accessible, router reachable).
"""
from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from pulse.cli.runtime import bootstrap


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal handler: GET / returns 200 with Pulse status JSON."""

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        try:
            rt = bootstrap()
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
            rt.storage.close()
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
    print(f"pulse health server on :{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
