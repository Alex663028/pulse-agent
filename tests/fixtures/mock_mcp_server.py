#!/usr/bin/env python3
"""A minimal but spec-compliant MCP stdio server for testing Pulse's client.

It speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and implements:
  - initialize
  - notifications/initialized (ignored)
  - tools/list  (one tool: "echo")
  - tools/call  (echo returns its "msg" argument)

Run as: python mock_mcp_server.py
"""
import json
import sys


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> None:
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp", "version": "1.0.0"},
            },
        })
    elif method == "notifications/initialized":
        return  # no response
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo a message back.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"msg": {"type": "string"}},
                            "required": ["msg"],
                        },
                    },
                    {
                        "name": "reverse",
                        "description": "Reverse a string.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                ]
            },
        })
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "echo":
            text = args.get("msg", "")
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": False}})
        elif name == "reverse":
            text = args.get("text", "")[::-1]
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": False}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(req)


if __name__ == "__main__":
    main()
