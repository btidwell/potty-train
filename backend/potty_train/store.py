"""Persist the log as one JSON document.

Production uses a private S3 object. Local development uses a file so the
same handler can run without AWS.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from potty_train.service import default_state


class Conflict(Exception):
    """Another save landed first."""


class StateStore(Protocol):
    def load(self) -> tuple[dict[str, Any], str]: ...

    def save(self, state: dict[str, Any], etag: str) -> str: ...


class FileStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> tuple[dict[str, Any], str]:
        with self._lock:
            if not self.path.exists():
                return default_state(), ""
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            etag = str(raw.pop("_rev", ""))
            return raw, etag

    def save(self, state: dict[str, Any], etag: str) -> str:
        with self._lock:
            current = ""
            if self.path.exists():
                current = str(json.loads(self.path.read_text(encoding="utf-8")).get("_rev", ""))
            if current != etag:
                raise Conflict()
            revision = str(int(current or "0") + 1)
            body = dict(state)
            body["_rev"] = revision
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return revision


class S3Store:
    def __init__(self, bucket: str, key: str) -> None:
        import boto3

        self.bucket = bucket
        self.key = key
        self.client = boto3.client("s3")

    def load(self) -> tuple[dict[str, Any], str]:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.key)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            # A missing object is AccessDenied when the role has no s3:ListBucket.
            if code in {"NoSuchKey", "404", "NotFound", "AccessDenied", "403"}:
                return default_state(), ""
            raise
        raw = json.loads(response["Body"].read().decode("utf-8"))
        raw.pop("_rev", None)
        return raw, response["ETag"]

    def save(self, state: dict[str, Any], etag: str) -> str:
        from botocore.exceptions import ClientError

        payload = json.dumps(state).encode("utf-8")
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self.key,
            "Body": payload,
            "ContentType": "application/json",
        }
        if etag:
            kwargs["IfMatch"] = etag
        else:
            kwargs["IfNoneMatch"] = "*"
        try:
            response = self.client.put_object(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in {"PreconditionFailed", "ConditionalRequestConflict", "412"}:
                raise Conflict() from exc
            raise
        return response["ETag"]


def build_store() -> StateStore:
    if os.environ.get("POTTY_ENV") == "local":
        path = os.environ.get("POTTY_STATE_PATH", "backend/.local-state.json")
        return FileStore(path)
    bucket = os.environ["DATA_BUCKET"]
    key = os.environ.get("STATE_KEY", "state/potty-log.json")
    return S3Store(bucket, key)
