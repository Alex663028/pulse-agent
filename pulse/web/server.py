"""Web UI — Flask-based session management dashboard on port 10000."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any


logger = logging.getLogger(__name__)


class DependencyError(RuntimeError):
    """Raised when an optional dependency is missing."""


DEFAULT_PORT = 10000

try:
    from flask import Flask, render_template_string, request, jsonify, redirect, url_for
except ImportError as exc:
    raise DependencyError("Flask not installed. Install with: pip install flask") from exc

from pulse.cli.runtime import Runtime, bootstrap  # noqa: E402


# ---- HTML templates ----

BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pulse Agent</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
    .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
    h1 { font-size: 1.5rem; margin-bottom: 1rem; color: #fff; }
    h2 { font-size: 1.2rem; margin-bottom: 0.75rem; color: #cbd5e1; }
    .nav { display: flex; gap: 1rem; margin-bottom: 2rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }
    .nav a { color: #94a3b8; text-decoration: none; padding: 0.5rem 0; border-bottom: 2px solid transparent; }
    .nav a:hover, .nav a.active { color: #fff; border-bottom-color: #6366f1; }
    .card { background: #1e293b; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; border: 1px solid #334155; }
    .session-item { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; border-bottom: 1px solid #334155; cursor: pointer; }
    .session-item:hover { background: #334155; }
    .session-item:last-child { border-bottom: none; }
    .btn { background: #6366f1; color: #fff; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
    .btn:hover { background: #4f46e5; }
    .btn-danger { background: #dc2626; }
    .btn-danger:hover { background: #b91c1c; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.8rem; }
    input[type="text"], input[type="number"], textarea, select {
      background: #0f172a; border: 1px solid #475569; color: #e2e8f0; padding: 0.5rem; border-radius: 4px; width: 100%;
    }
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; margin-bottom: 0.25rem; color: #94a3b8; font-size: 0.9rem; }
    .chat-container { display: flex; flex-direction: column; height: 70vh; }
    .chat-messages { flex: 1; overflow-y: auto; padding: 1rem; background: #0f172a; border-radius: 4px; margin-bottom: 1rem; }
    .message { margin-bottom: 1rem; padding: 0.75rem; border-radius: 8px; }
    .message.user { background: #1e3a5f; margin-left: 2rem; }
    .message.assistant { background: #1e293b; margin-right: 2rem; border: 1px solid #334155; }
    .message .role { font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.25rem; }
    .chat-input { display: flex; gap: 0.5rem; }
    .chat-input input { flex: 1; }
    .tool-item { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid #334155; }
    .tool-item:last-child { border-bottom: none; }
    .badge { background: #334155; color: #94a3b8; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.75rem; }
    .badge.enabled { background: #065f46; color: #a7f3d0; }
    .badge.disabled { background: #7f1d1d; color: #fecaca; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 1rem; }
    .stat { text-align: center; padding: 1rem; }
    .stat .value { font-size: 2rem; font-weight: bold; color: #fff; }
    .stat .label { color: #94a3b8; font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Pulse Agent</h1>
    <nav class="nav">
      <a href="/" class="{{ 'active' if active_page == 'sessions' else '' }}">Sessions</a>
      <a href="/tools" class="{{ 'active' if active_page == 'tools' else '' }}">Tools</a>
      <a href="/settings" class="{{ 'active' if active_page == 'settings' else '' }}">Settings</a>
    </nav>
    {{ content }}
  </div>
</body>
</html>
"""

SESSIONS_TEMPLATE = """
<div class="grid" style="margin-bottom: 2rem;">
  <div class="card stat">
    <div class="value">{{ stats.sessions }}</div>
    <div class="label">Active Sessions</div>
  </div>
  <div class="card stat">
    <div class="value">{{ stats.tools }}</div>
    <div class="label">Available Tools</div>
  </div>
  <div class="card stat">
    <div class="value">{{ stats.provider }}</div>
    <div class="label">Provider</div>
  </div>
  <div class="card stat">
    <div class="value">{{ stats.model }}</div>
    <div class="label">Model</div>
  </div>
</div>

<h2>Sessions</h2>
<div class="card">
  <div style="margin-bottom: 1rem;">
    <form method="post" action="/api/sessions" style="display: flex; gap: 0.5rem;">
      <input type="text" name="name" placeholder="New session name..." required>
      <button type="submit" class="btn">Create</button>
    </form>
  </div>
  {% if sessions %}
    {% for s in sessions %}
    <div class="session-item">
      <div>
        <strong>{{ s.name }}</strong>
        <span class="badge">{{ s.message_count }} msgs</span>
        <span style="color: #64748b; font-size: 0.8rem;">{{ s.last_activity }}</span>
      </div>
      <div style="display: flex; gap: 0.5rem;">
        <a href="/chat/{{ s.id }}" class="btn btn-sm">Open</a>
        <form method="post" action="/api/sessions/{{ s.id }}/delete" style="display: inline;">
          <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</button>
        </form>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <p style="color: #64748b; text-align: center; padding: 2rem;">No sessions yet. Create one above.</p>
  {% endif %}
</div>
"""

CHAT_TEMPLATE = """
<div class="chat-container">
  <div class="chat-messages" id="messages">
    {% for m in messages %}
    <div class="message {{ m.role }}">
      <div class="role">{{ m.role }}</div>
      <div>{{ m.content }}</div>
    </div>
    {% endfor %}
  </div>
  <form class="chat-input" id="chatForm">
    <input type="text" id="messageInput" placeholder="Type a message..." autofocus>
    <button type="submit" class="btn">Send</button>
  </form>
</div>
<script>
const form = document.getElementById('chatForm');
const input = document.getElementById('messageInput');
const msgs = document.getElementById('messages');

form.onsubmit = async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  const userDiv = document.createElement('div');
  userDiv.className = 'message user';
  userDiv.innerHTML = '<div class="role">you</div><div>' + text + '</div>';
  msgs.appendChild(userDiv);
  msgs.scrollTop = msgs.scrollHeight;

  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: '{{ session_id }}', message: text})
  });
  const data = await res.json();

  const asstDiv = document.createElement('div');
  asstDiv.className = 'message assistant';
  asstDiv.innerHTML = '<div class="role">pulse</div><div>' + (data.answer || data.error || '(empty)') + '</div>';
  msgs.appendChild(asstDiv);
  msgs.scrollTop = msgs.scrollHeight;
};
</script>
"""

TOOLS_TEMPLATE = """
<h2>Tools</h2>
<div class="card">
  <p style="margin-bottom: 1rem; color: #94a3b8;">Enable or disable tools. Changes apply to new sessions.</p>
  {% for t in tools %}
  <div class="tool-item">
    <div>
      <strong>{{ t.name }}</strong>
      <div style="color: #64748b; font-size: 0.85rem;">{{ t.description }}</div>
    </div>
    <span class="badge {{ 'enabled' if t.enabled else 'disabled' }}">
      {{ 'enabled' if t.enabled else 'disabled' }}
    </span>
  </div>
  {% endfor %}
</div>
"""

SETTINGS_TEMPLATE = """
<h2>Settings</h2>
<div class="card">
  <form method="post" action="/api/settings">
    <div class="form-group">
      <label>Provider</label>
      <select name="provider">
        {% for p in providers %}
        <option value="{{ p }}" {{ 'selected' if p == current.provider else '' }}>{{ p }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="form-group">
      <label>Model</label>
      <input type="text" name="model" value="{{ current.model }}">
    </div>
    <div class="form-group">
      <label>Base URL</label>
      <input type="text" name="base_url" value="{{ current.base_url }}">
    </div>
    <div class="form-group">
      <label>Max Session Tokens</label>
      <input type="number" name="max_session_tokens" value="{{ current.max_session_tokens }}">
    </div>
    <button type="submit" class="btn">Save</button>
  </form>
</div>
"""


# ---- App factory ----

class PulseWebUI:
    """Encapsulate the Flask dashboard, routes, and in-memory session state."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.sessions: dict[str, dict[str, Any]] = {}
        self.sessions_lock = threading.Lock()
        self.app = Flask(__name__)
        self._register_routes()

    def _get_session(self, sid: str) -> dict[str, Any] | None:
        with self.sessions_lock:
            return self.sessions.get(sid)

    def _create_session(self, name: str) -> str:
        import uuid

        sid = f"sess_{uuid.uuid4().hex[:12]}"
        with self.sessions_lock:
            self.sessions[sid] = {
                "id": sid,
                "name": name,
                "messages": [],
                "created_at": datetime.now().isoformat(),
            }
        return sid

    def _delete_session(self, sid: str) -> None:
        with self.sessions_lock:
            self.sessions.pop(sid, None)
        self.runtime.orchestrator.clear_session(sid)

    def _get_all_sessions(self) -> list[dict[str, Any]]:
        with self.sessions_lock:
            return [
                {
                    "id": sid,
                    "name": s["name"],
                    "message_count": len(s["messages"]),
                    "last_activity": s["created_at"][:19],
                }
                for sid, s in self.sessions.items()
            ]

    def _render(self, page: str, **kwargs) -> str:
        return render_template_string(
            BASE_TEMPLATE,
            active_page=page,
            content=render_template_string(kwargs.pop("template"), **kwargs),
        )

    @staticmethod
    def _stats(runtime: Runtime, sessions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "sessions": len(sessions),
            "tools": len(runtime.tools.schemas()),
            "provider": runtime.settings.model.provider,
            "model": runtime.settings.model.model,
        }

    def _register_routes(self) -> None:
        app = self.app
        app.add_url_rule("/", "index", self._route_index)
        app.add_url_rule("/chat/<session_id>", "chat", self._route_chat)
        app.add_url_rule("/tools", "tools", self._route_tools)
        app.add_url_rule("/settings", "settings", self._route_settings)
        app.add_url_rule("/api/sessions", "api_create_session", self._route_api_create_session, methods=["POST"])
        app.add_url_rule("/api/sessions/<session_id>/delete", "api_delete_session", self._route_api_delete_session, methods=["POST"])
        app.add_url_rule("/api/chat", "api_chat", self._route_api_chat, methods=["POST"])
        app.add_url_rule("/api/tools", "api_tools", self._route_api_tools, methods=["GET"])

    def _route_index(self):
        return self._render(
            "sessions",
            template=SESSIONS_TEMPLATE,
            sessions=self._get_all_sessions(),
            stats=self._stats(self.runtime, self.sessions),
        )

    def _route_chat(self, session_id: str):
        s = self._get_session(session_id)
        if not s:
            return redirect(url_for("index"))
        return self._render(
            "sessions",
            template=CHAT_TEMPLATE,
            session_id=session_id,
            messages=s["messages"],
        )

    def _route_tools(self):
        schemas = self.runtime.tools.schemas()
        tool_list = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"][:80],
                "enabled": True,
            }
            for t in schemas
        ]
        return self._render("tools", template=TOOLS_TEMPLATE, tools=tool_list)

    def _route_settings(self):
        return self._render(
            "settings",
            template=SETTINGS_TEMPLATE,
            current={
                "provider": self.runtime.settings.model.provider,
                "model": self.runtime.settings.model.model,
                "base_url": self.runtime.settings.model.base_url,
                "max_session_tokens": self.runtime.settings.max_session_tokens,
            },
            providers=["ollama", "openai", "openrouter", "deepseek", "anthropic", "mock"],
        )

    def _route_api_create_session(self):
        name = request.form.get("name") or request.json.get("name") or "Untitled"
        sid = self._create_session(name)
        return redirect(url_for("chat", session_id=sid))

    def _route_api_delete_session(self, session_id: str):
        self._delete_session(session_id)
        return redirect(url_for("index"))

    def _route_api_chat(self):
        data = request.get_json()
        if not data:
            return jsonify({"error": "no JSON body"}), 400
        sid = data.get("session_id") or self._create_session("New Chat")
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "empty message"}), 400

        s = self._get_session(sid)
        if not s:
            return jsonify({"error": "session not found"}), 404

        s["messages"].append({"role": "user", "content": message})

        try:
            result = self.runtime.orchestrator.run(message, session_id=sid)
            answer = result.answer if result.success else f"Error: {result.error}"
        except Exception as e:
            logger.exception("web chat failed")
            answer = f"Error: {e}"

        s["messages"].append({"role": "assistant", "content": answer})
        return jsonify({"answer": answer, "session_id": sid})

    def _route_api_tools(self):
        return jsonify({"tools": self.runtime.tools.schemas()})


def create_app() -> Flask:
    """Create and configure the Flask app."""
    return PulseWebUI(bootstrap(load_mcp=True)).app


def main():
    """Entry point for `pulse web`."""
    import argparse

    parser = argparse.ArgumentParser(description="Pulse Web UI")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    logger.info("Pulse Web UI running on http://%s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
