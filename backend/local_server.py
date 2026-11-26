"""Run the Lambda handler on localhost for the Angular dev server.

This is a development stand-in. Production is the Lambda function in infra/.
Sign-in uses the Cognito user pool. Terraform writes the pool ids to
backend/.local-cognito.json.
"""

from __future__ import annotations

import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".local-state.json"
SESSIONS_PATH = ROOT / ".local-sessions.json"
COGNITO_PATH = ROOT / ".local-cognito.json"


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


def main() -> None:
    os.environ["POTTY_ENV"] = "local"
    os.environ["POTTY_STATE_PATH"] = str(STATE_PATH)
    os.environ["POTTY_SESSIONS_PATH"] = str(SESSIONS_PATH)
    os.environ.setdefault("CORS_ORIGIN", "http://localhost:4200")
    _load_cognito()

    from potty_train.handler import handler

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
            result = handler(event, None)
            body = result.get("body") or ""
            # The PDF route is base64, the same way a Lambda function URL
            # returns a binary body. Everything else is JSON or CSV text.
            if result.get("isBase64Encoded"):
                raw = base64.b64decode(body)
            else:
                raw = body.encode("utf-8")
            body = raw
            self.send_response(int(result["statusCode"]))
            for key, value in (result.get("headers") or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
