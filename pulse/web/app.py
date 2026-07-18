"""Web UI server with modern frontend (Flask + React SPA)."""

from __future__ import annotations

import logging
from typing import Any

from pulse.cli.runtime import Runtime, bootstrap

logger = logging.getLogger(__name__)

DEFAULT_PORT = 10000

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pulse Agent</title>
<script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
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
</style>
</head>
<body>
<div id="root"></div>
<script type="text/babel">
const { useState, useEffect, useRef, createContext, useContext } = React;

// API helper
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  return res.json();
}

// Main App
function App() {
  const [page, setPage] = useState('chat');
  const [sessions, setSessions] = useState([]);
  const [tools, setTools] = useState([]);
  const [provider, setProvider] = useState({});

  useEffect(() => {
    api('GET', '/sessions').then(setSessions);
    api('GET', '/tools').then(setTools);
    api('GET', '/status').then(setProvider);
  }, []);

  return (
    <div className="app">
      <div className="sidebar">
        <div className="sidebar-header"><h2>Pulse Agent</h2></div>
        <div className={`nav-item ${page === 'chat' ? 'active' : ''}`} onClick={() => setPage('chat')}>Chat</div>
        <div className={`nav-item ${page === 'sessions' ? 'active' : ''}`} onClick={() => setPage('sessions')}>Sessions</div>
        <div className={`nav-item ${page === 'tools' ? 'active' : ''}`} onClick={() => setPage('tools')}>Tools</div>
        <div className={`nav-item ${page === 'skills' ? 'active' : ''}`} onClick={() => setPage('skills')}>Skills</div>
      </div>
      <div className="main">
        <div className="header">
          <h2>{page.charAt(0).toUpperCase() + page.slice(1)}</h2>
        </div>
        <div className="content">
          {page === 'chat' && <ChatPage />}
          {page === 'sessions' && <SessionsPage sessions={sessions} onRefresh={() => api('GET', '/sessions').then(setSessions)} />}
          {page === 'tools' && <ToolsPage tools={tools} />}
          {page === 'skills' && <SkillsPage />}
        </div>
      </div>
    </div>
  );
}

// Chat Page
function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const messagesEnd = useRef(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async () => {
    if (!input.trim()) return;
    const userMsg = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    const res = await api('POST', '/chat', { session_id: sessionId, message: input });
    if (res.session_id) setSessionId(res.session_id);
    setMessages(prev => [...prev, { role: 'assistant', content: res.answer || res.error || '...' }]);
  };

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.length === 0 && <p style={{color:'#64748b',textAlign:'center',padding:'2rem'}}>Start a conversation...</p>}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <div className="role">{m.role}</div>
            <div>{m.content}</div>
          </div>
        ))}
        <div ref={messagesEnd} />
      </div>
      <div className="chat-input">
        <input className="input" placeholder="Type a message..." value={input}
               onChange={e => setInput(e.target.value)}
               onKeyDown={e => e.key === 'Enter' && send()} />
        <button className="btn" onClick={send}>Send</button>
      </div>
    </div>
  );
}

// Sessions Page
function SessionsPage({ sessions, onRefresh }) {
  const del = async (id) => { await api('DELETE', '/sessions/' + id); onRefresh(); };
  return (
    <div className="card">
      <h3>Sessions ({sessions.length})</h3>
      <div className="sessions-list">
        {sessions.length === 0 && <p style={{color:'#64748b'}}>No sessions yet</p>}
        {sessions.map(s => (
          <div key={s.id} className="session-item">
            <div><strong>{s.name}</strong> <span className="badge">{s.message_count} msgs</span></div>
            <button className="btn btn-danger" onClick={() => del(s.id)}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// Tools Page
function ToolsPage({ tools }) {
  return (
    <div className="card">
      <h3>Available Tools ({tools.length})</h3>
      {tools.map((t, i) => (
        <div key={i} className="session-item">
          <div><strong>{t.name}</strong> <span style={{color:'#64748b',fontSize:'0.85rem'}}>{t.description}</span></div>
          <span className={`badge ${t.enabled !== false ? 'success' : 'error'}`}>
            {t.enabled !== false ? 'enabled' : 'disabled'}
          </span>
        </div>
      ))}
    </div>
  );
}

// Skills Page
function SkillsPage() {
  const [skills, setSkills] = useState([]);
  useEffect(() => { api('GET', '/skills').then(setSkills); }, []);
  return (
    <div className="card">
      <h3>Skills ({skills.length})</h3>
      {skills.map((s, i) => (
        <div key={i} className="session-item">
          <div><strong>{s.name}</strong> <span className="badge">{s.status}</span></div>
          <span style={{color:'#64748b',fontSize:'0.85rem'}}>v{s.version}</span>
        </div>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
"""


def create_web_app(rt: Runtime | None = None) -> Any:
    from flask import Flask, request, jsonify

    app = Flask(__name__)
    _rt = rt or bootstrap(load_mcp=True)

    @app.route("/")
    def index():
        return INDEX_HTML

    @app.route("/api/status")
    def status():
        return jsonify(
            {
                "provider": _rt.settings.model.provider,
                "model": _rt.settings.model.model,
                "sessions": len(_rt.storage.sessions_map)
                if hasattr(_rt.storage, "sessions_map")
                else 0,
                "tools": len(_rt.tools.allowed_names),
            }
        )

    @app.route("/api/sessions", methods=["GET"])
    def list_sessions():
        sessions = (
            _rt.storage.list_sessions() if hasattr(_rt.storage, "list_sessions") else []
        )
        return jsonify(sessions)

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id):
        if hasattr(_rt.storage, "delete_session"):
            _rt.storage.delete_session(session_id)
        return jsonify({"ok": True})

    @app.route("/api/tools")
    def list_tools():
        return jsonify(
            [
                {
                    "name": n,
                    "description": _rt.tools.get(n).description
                    if _rt.tools.get(n)
                    else "",
                    "enabled": True,
                }
                for n in _rt.tools.allowed_names
            ]
        )

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.json or {}
        sid = data.get("session_id")
        msg = data.get("message", "")
        if not msg:
            return jsonify({"error": "empty message"}), 400
        try:
            res = _rt.orchestrator.run(msg, session_id=sid)
            return jsonify(
                {
                    "session_id": res.session_id,
                    "answer": res.answer,
                    "trace_id": res.trace_id,
                    "success": res.success,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/skills")
    def list_skills():
        return jsonify(
            [
                {
                    "name": r["name"],
                    "status": r["status"],
                    "version": r.get("version", "?"),
                }
                for r in _rt.registry.list()
            ]
        )

    return app


def main(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    app = create_web_app()
    logger.info("Pulse Web UI on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
