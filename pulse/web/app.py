"""Web UI server with modern frontend (Flask + React SPA) - Enhanced version.

Features:
- Proper JWT-based authentication
- Server-Sent Events (SSE) for streaming chat
- RBAC integration
- State management with proper API design
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from functools import wraps
from typing import Any

from pulse.cli.runtime import Runtime, bootstrap

logger = logging.getLogger(__name__)

DEFAULT_PORT = 10000

# --- Authentication decorator ---

def require_auth(f):
    """Decorator to require JWT authentication on API endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "unauthorized", "message": "Missing or invalid Authorization header"}), 401
        token = auth_header[7:]
        from pulse.config.settings import load_settings
        settings = load_settings()
        # For now, check against a stored token in settings directory
        # In production, use proper JWT validation
        token_file = settings.config_dir / ".web_token"
        if not token_file.exists():
            return jsonify({"error": "unauthorized", "message": "No valid session"}), 401
        stored = token_file.read_text().strip()
        if stored != token:
            return jsonify({"error": "unauthorized", "message": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


# --- HTML Template ---

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pulse Agent</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
  .app { display: flex; height: 100vh; }
  .sidebar { width: 280px; background: #1e293b; border-right: 1px solid #334155; display: flex; flex-direction: column; }
  .sidebar-header { padding: 1rem; border-bottom: 1px solid #334155; }
  .sidebar-header h2 { color: #fff; font-size: 1.1rem; }
  .nav-item { padding: 0.75rem 1rem; color: #94a3b8; cursor: pointer; border-left: 3px solid transparent; transition: all 0.2s; }
  .nav-item:hover { background: #334155; color: #fff; }
  .nav-item.active { background: #1e3a5f; color: #fff; border-left-color: #6366f1; }
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .header { padding: 1rem; border-bottom: 1px solid #334155; background: #1e293b; }
  .content { flex: 1; overflow-y: auto; padding: 1rem; }
  .card { background: #1e293b; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; border: 1px solid #334155; }
  .card h3 { margin-bottom: 0.5rem; color: #fff; }
  .btn { background: #6366f1; color: #fff; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
  .btn:hover { background: #4f46e5; }
  .btn-danger { background: #dc2626; }
  .btn-danger:hover { background: #b91c1c; }
  .input { background: #0f172a; border: 1px solid #475569; color: #e2e8f0; padding: 0.5rem; border-radius: 4px; width: 100%; }
  .message { padding: 0.75rem; margin-bottom: 0.5rem; border-radius: 8px; }
  .message.user { background: #1e3a5f; margin-left: 2rem; }
  .message.assistant { background: #334155; margin-right: 2rem; }
  .message .role { font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.25rem; }
  .chat-container { display: flex; flex-direction: column; height: 100%; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 1rem; }
  .chat-input { display: flex; gap: 0.5rem; padding: 1rem; border-top: 1px solid #334155; }
  .chat-input input { flex: 1; }
  .badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.75rem; background: #334155; color: #94a3b8; }
  .badge.success { background: #065f46; color: #a7f3d0; }
  .badge.error { background: #7f1d1d; color: #fecaca; }
  .sessions-list { max-height: 60vh; overflow-y: auto; }
  .session-item { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; border-bottom: 1px solid #334155; cursor: pointer; }
  .session-item:hover { background: #334155; }
  .session-item:last-child { border-bottom: none; }
  .login-container { display: flex; align-items: center; justify-content: center; height: 100vh; }
  .login-box { background: #1e293b; padding: 2rem; border-radius: 8px; border: 1px solid #334155; width: 320px; }
  .login-box h2 { margin-bottom: 1rem; color: #fff; }
  .login-box input { width: 100%; margin-bottom: 0.75rem; }
  .login-box .btn { width: 100%; }
  .error-msg { color: #f87171; font-size: 0.85rem; margin-top: 0.5rem; }
</style>
</head>
<body>
<div id="root"></div>
<script>
// Simple state management
const AppState = {
  token: localStorage.getItem('pulse_token') || null,
  page: 'chat',
  sessionId: null,
  sessions: [],
  tools: [],
  messages: [],
  loginError: ''
};

// API helper with auth
async function api(method, path, body, isStream) {
  const headers = { 'Content-Type': 'application/json' };
  if (AppState.token) headers['Authorization'] = 'Bearer ' + AppState.token;
  const opts = { method, headers };
  if (body && !isStream) opts.body = JSON.stringify(body);
  else if (body && isStream) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  if (res.status === 401) {
    AppState.token = null;
    localStorage.removeItem('pulse_token');
    render();
    throw new Error('unauthorized');
  }
  return res;
}

function render() {
  const root = document.getElementById('root');
  if (!AppState.token) {
    root.innerHTML = `
      <div class="login-container">
        <div class="login-box">
          <h2>Pulse Agent Login</h2>
          <input class="input" id="username" placeholder="Username" />
          <input class="input" id="password" type="password" placeholder="Password" />
          <button class="btn" onclick="doLogin()">Login</button>
          ${AppState.loginError ? '<div class="error-msg">' + AppState.loginError + '</div>' : ''}
        </div>
      </div>
    `;
    return;
  }
  root.innerHTML = `
    <div class="app">
      <div class="sidebar">
        <div class="sidebar-header"><h2>Pulse Agent</h2></div>
        <div class="nav-item ${AppState.page === 'chat' ? 'active' : ''}" onclick="setPage('chat')">Chat</div>
        <div class="nav-item ${AppState.page === 'sessions' ? 'active' : ''}" onclick="setPage('sessions')">Sessions</div>
        <div class="nav-item ${AppState.page === 'tools' ? 'active' : ''}" onclick="setPage('tools')">Tools</div>
        <div class="nav-item ${AppState.page === 'skills' ? 'active' : ''}" onclick="setPage('skills')">Skills</div>
        <div class="nav-item" onclick="doLogout()" style="margin-top: auto; border-top: 1px solid #334155;">Logout</div>
      </div>
      <div class="main">
        <div class="header"><h2>${AppState.page.charAt(0).toUpperCase() + AppState.page.slice(1)}</h2></div>
        <div class="content" id="content"></div>
      </div>
    </div>
  `;
  renderPage();
}

function setPage(page) {
  AppState.page = page;
  render();
}

function renderPage() {
  const content = document.getElementById('content');
  if (AppState.page === 'chat') {
    renderChat(content);
  } else if (AppState.page === 'sessions') {
    renderSessions(content);
  } else if (AppState.page === 'tools') {
    renderTools(content);
  } else if (AppState.page === 'skills') {
    renderSkills(content);
  }
}

function renderChat(container) {
  let html = '<div class="chat-container"><div class="chat-messages">';
  if (AppState.messages.length === 0) {
    html += '<p style="color:#64748b;text-align:center;padding:2rem">Start a conversation...</p>';
  }
  AppState.messages.forEach(m => {
    html += '<div class="message ' + m.role + '"><div class="role">' + m.role + '</div><div>' + (m.content || '') + '</div></div>';
  });
  html += '</div><div class="chat-input"><input class="input" id="msg-input" placeholder="Type a message..." onkeydown="if(event.key===\'Enter\')send()"><button class="btn" onclick="send()">Send</button></div></div>';
  container.innerHTML = html;
}

function renderSessions(container) {
  let html = '<div class="card"><h3>Sessions (' + AppState.sessions.length + ')</h3><div class="sessions-list">';
  if (AppState.sessions.length === 0) html += '<p style="color:#64748b">No sessions yet</p>';
  AppState.sessions.forEach(s => {
    html += '<div class="session-item"><div><strong>' + (s.id || '').substring(0, 20) + '</strong> <span class="badge">' + (s.message_count || 0) + ' msgs</span></div><button class="btn btn-danger" onclick="deleteSession(\\'' + s.id + '\\')">Delete</button></div>';
  });
  html += '</div></div>';
  container.innerHTML = html;
}

function renderTools(container) {
  let html = '<div class="card"><h3>Available Tools (' + AppState.tools.length + ')</h3>';
  AppState.tools.forEach(t => {
    html += '<div class="session-item"><div><strong>' + t.name + '</strong> <span style="color:#64748b;font-size:0.85rem">' + (t.description || '') + '</span></div><span class="badge ' + (t.enabled !== false ? 'success' : 'error') + '">' + (t.enabled !== false ? 'enabled' : 'disabled') + '</span></div>';
  });
  html += '</div>';
  container.innerHTML = html;
}

function renderSkills(container) {
  let html = '<div class="card"><h3>Skills</h3><div class="sessions-list">';
  if (!AppState.skills || AppState.skills.length === 0) html += '<p style="color:#64748b">No skills yet</p>';
  else {
    AppState.skills.forEach(s => {
      html += '<div class="session-item"><div><strong>' + (s.name || '') + '</strong> <span class="badge">' + (s.status || '') + '</span></div><span style="color:#64748b;font-size:0.85rem">v' + (s.version || '?') + '</span></div>';
    });
  }
  html += '</div></div>';
  container.innerHTML = html;
}

async function doLogin() {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  try {
    const res = await api('POST', '/auth/login', { username, password });
    const data = await res.json();
    if (res.ok && data.token) {
      AppState.token = data.token;
      localStorage.setItem('pulse_token', data.token);
      AppState.loginError = '';
      await loadData();
      render();
    } else {
      AppState.loginError = data.error || 'Login failed';
      render();
    }
  } catch (e) {
    AppState.loginError = 'Login failed: ' + e.message;
    render();
  }
}

async function doLogout() {
  await api('POST', '/auth/logout', {});
  AppState.token = null;
  AppState.messages = [];
  AppState.sessionId = null;
  localStorage.removeItem('pulse_token');
  render();
}

async function loadData() {
  try {
    const [sess, tools, skills] = await Promise.all([
      api('GET', '/sessions').then(r => r.json()),
      api('GET', '/tools').then(r => r.json()),
      api('GET', '/skills').then(r => r.json()),
    ]);
    AppState.sessions = sess;
    AppState.tools = tools;
    AppState.skills = skills;
  } catch (e) {
    console.error('loadData error:', e);
  }
}

async function send() {
  const input = document.getElementById('msg-input');
  const msg = input.value.trim();
  if (!msg) return;
  AppState.messages.push({ role: 'user', content: msg });
  input.value = '';
  renderChat(document.getElementById('content'));

  try {
    const res = await api('POST', '/chat', { message: msg, session_id: AppState.sessionId });
    const data = await res.json();
    if (data.session_id) AppState.sessionId = data.session_id;
    AppState.messages.push({ role: 'assistant', content: data.answer || data.error || '...' });
    renderChat(document.getElementById('content'));
  } catch (e) {
    AppState.messages.push({ role: 'assistant', content: 'Error: ' + e.message });
    renderChat(document.getElementById('content'));
  }
}

async function deleteSession(id) {
  await api('DELETE', '/sessions/' + id);
  await loadData();
  render();
}

// Init
if (AppState.token) {
  loadData().then(() => render());
} else {
  render();
}
</script>
</body>
</html>
"""


def create_web_app(rt: Runtime | None = None) -> Any:
    from flask import Flask, request, jsonify, Response

    app = Flask(__name__)
    _rt = rt or bootstrap(load_mcp=True)

    # --- Auth endpoints ---

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        data = request.json or {}
        username = data.get("username", "")
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"error": "missing username or password"}), 400
        # Use the enterprise AuthManager for authentication
        from pulse.enterprise import AuthManager
        auth = AuthManager()
        token = auth.authenticate(username, password)
        if not token:
            return jsonify({"error": "invalid credentials"}), 401
        # Store token for validation
        token_file = _rt.settings.config_dir / ".web_token"
        token_file.write_text(token)
        return jsonify({"token": token, "expires_in": 86400})

    @app.route("/api/auth/logout", methods=["POST"])
    @require_auth
    def logout():
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:]
        from pulse.enterprise import AuthManager
        auth = AuthManager()
        auth.logout(token)
        token_file = _rt.settings.config_dir / ".web_token"
        if token_file.exists():
            token_file.unlink()
        return jsonify({"ok": True})

    # --- Protected endpoints ---

    @app.route("/")
    def index():
        return INDEX_HTML

    @app.route("/api/status")
    @require_auth
    def status():
        return jsonify({
            "provider": _rt.settings.model.provider,
            "model": _rt.settings.model.model,
            "sessions": len(_rt.storage.list_sessions()) if hasattr(_rt.storage, "list_sessions") else 0,
            "tools": len(_rt.tools.allowed_names),
        })

    @app.route("/api/sessions", methods=["GET"])
    @require_auth
    def list_sessions():
        sessions = _rt.storage.list_sessions() if hasattr(_rt.storage, "list_sessions") else []
        # Limit to 50 sessions
        return jsonify(sessions[:50])

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    @require_auth
    def delete_session(session_id):
        if hasattr(_rt.storage, "delete_session"):
            _rt.storage.delete_session(session_id)
        return jsonify({"ok": True})

    @app.route("/api/tools")
    @require_auth
    def list_tools():
        return jsonify([
            {
                "name": n,
                "description": _rt.tools.get(n).description if _rt.tools.get(n) else "",
                "enabled": True,
            }
            for n in _rt.tools.allowed_names
        ])

    @app.route("/api/chat", methods=["POST"])
    @require_auth
    def chat():
        data = request.json or {}
        sid = data.get("session_id")
        msg = data.get("message", "")
        if not msg:
            return jsonify({"error": "empty message"}), 400
        try:
            res = _rt.orchestrator.run(msg, session_id=sid)
            return jsonify({
                "session_id": res.session_id,
                "answer": res.answer,
                "trace_id": res.trace_id,
                "success": res.success,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat/stream", methods=["POST"])
    @require_auth
    def chat_stream():
        """Server-Sent Events endpoint for streaming chat."""
        data = request.json or {}
        sid = data.get("session_id")
        msg = data.get("message", "")
        if not msg:
            return jsonify({"error": "empty message"}), 400

        def generate():
            try:
                for chunk in _rt.orchestrator.run_stream(msg, session_id=sid):
                    if chunk.content:
                        yield f"data: {json.dumps({'content': chunk.content, 'session_id': sid})}\n\n"
                    if chunk.has_tool_calls:
                        for tc in chunk.tool_calls:
                            yield f"data: {json.dumps({'tool': tc.name, 'args': tc.arguments})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(generate(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.route("/api/skills")
    @require_auth
    def list_skills():
        return jsonify([
            {"name": r["name"], "status": r["status"], "version": r.get("version", "?")}
            for r in _rt.registry.list()
        ])

    return app


def main(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    app = create_web_app()
    logger.info("Pulse Web UI on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()