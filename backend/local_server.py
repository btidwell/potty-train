"""Run the Lambda handler on localhost for the Angular dev server.

This is a development stand-in. Production is the Lambda function in infra/.
"""

from __future__ import annotations

import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".local-state.json"
PASSWORD_PATH = ROOT / ".local-password"


def _ensure_password() -> str:
    existing = os.environ.get("POTTY_LOCAL_PASSWORD")
    if existing:
        return existing
    if PASSWORD_PATH.exists():
        password = PASSWORD_PATH.read_text(encoding="utf-8").strip()
    else:
        password = secrets.token_urlsafe(12)
        PASSWORD_PATH.write_text(password + "\n", encoding="utf-8")
    os.environ["POTTY_LOCAL_PASSWORD"] = password
    return password


def main() -> None:
    os.environ["POTTY_ENV"] = "local"
    os.environ["POTTY_STATE_PATH"] = str(STATE_PATH)
    os.environ.setdefault("POTTY_LOCAL_TOKEN_KEY", "local-dev-token-key")
    os.environ.setdefault("CORS_ORIGIN", "http://localhost:4200")
    password = _ensure_password()

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
            body = (result.get("body") or "").encode("utf-8")
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
    print(f"Local password: {password}", flush=True)
    print(f"State file: {STATE_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
