"""Run the Lambda handler on localhost for the Angular dev server.

This is a development stand-in. Production is the Lambda function in infra/.
Sign-in uses the Cognito user pool. Terraform writes the pool ids to
backend/.local-cognito.json.

Chat streams Server-Sent Events from /api/chat. MCP tools are available at
/mcp when the agent package is installed; otherwise the agent uses in-process
tools.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".local-state.json"
SESSIONS_PATH = ROOT / ".local-sessions.json"
COGNITO_PATH = ROOT / ".local-cognito.json"
SECRETS_PATH = ROOT / ".local-secrets.json"


def _load_cognito() -> None:
    if os.environ.get("COGNITO_USER_POOL_ID") and os.environ.get("COGNITO_CLIENT_ID"):
        return
    if not COGNITO_PATH.exists():
        print(
            "No Cognito config. Sign-in stays unavailable until "
            "terraform writes backend/.local-cognito.json.",
            flush=True,
        )
        return
    data = json.loads(COGNITO_PATH.read_text(encoding="utf-8"))
    os.environ["COGNITO_USER_POOL_ID"] = str(data["userPoolId"])
    os.environ["COGNITO_CLIENT_ID"] = str(data["userPoolClientId"])
    os.environ["COGNITO_REGION"] = str(data.get("region") or "us-east-1")


def _load_local_secrets() -> None:
    if not SECRETS_PATH.exists():
        return
    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    mapping = {
        "xai_api_key": "XAI_API_KEY",
        "vapid_private_pem": "POTTY_VAPID_PRIVATE_PEM",
        "vapid_public_pem": "POTTY_VAPID_PUBLIC_PEM",
    }
    for key, env_name in mapping.items():
        value = data.get(key)
        if value and not os.environ.get(env_name):
            os.environ[env_name] = str(value)


def main() -> None:
    os.environ["POTTY_ENV"] = "local"
    os.environ["POTTY_STATE_PATH"] = str(STATE_PATH)
    os.environ["POTTY_SESSIONS_PATH"] = str(SESSIONS_PATH)
    os.environ.setdefault("CORS_ORIGIN", "http://localhost:4200")
    _load_cognito()
    _load_local_secrets()

    from potty_train.handler import handler

    try:
        from potty_mcp.handler import handler as mcp_handler
    except ImportError:
        mcp_handler = None
        print("MCP package unavailable; /mcp will 404.", flush=True)

    try:
        from potty_agent.local import handle_chat_event
    except ImportError:
        handle_chat_event = None
        print("Agent package unavailable; /api/chat will 404.", flush=True)

    class AppHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            path = self.path.split("?", 1)[0]
            event = {
                "httpMethod": self.command,
                "path": path,
                "headers": {key: value for key, value in self.headers.items()},
                "body": raw,
            }

            if path in {"/api/chat", "/api/chat/"} and handle_chat_event is not None:
                self._chat(event)
                return
            if path in {"/mcp", "/mcp/"} and mcp_handler is not None:
                result = mcp_handler(event, None)
                self._write_result(result)
                return

            result = handler(event, None)
            self._write_result(result)

        def _chat(self, event: dict[str, Any]) -> None:
            assert handle_chat_event is not None
            result = handle_chat_event(event)
            if isinstance(result, dict):
                self._write_result(result)
                return
            self._write_sse(result)

        def _write_sse(self, chunks: Iterator[bytes]) -> None:
            self.send_response(200)
            origin = os.environ.get("CORS_ORIGIN", "")
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            try:
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except BrokenPipeError:
                pass

        def _write_result(self, result: dict[str, Any]) -> None:
            body = result.get("body") or ""
            # The PDF route is base64, the same way a Lambda function URL
            # returns a binary body. Everything else is JSON or CSV text.
            if result.get("isBase64Encoded"):
                raw_body = base64.b64decode(body)
            else:
                raw_body = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(int(result["statusCode"]))
            for key, value in (result.get("headers") or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw_body)))
            self.end_headers()
            self.wfile.write(raw_body)

        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.command} {self.path} {args[0] if args else ''}")

    server = ThreadingHTTPServer(("127.0.0.1", 8787), AppHandler)
    print("Potty Log API at http://127.0.0.1:8787", flush=True)
    print(f"State file: {STATE_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
