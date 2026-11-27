"""Upload the built UI to S3 and invalidate CloudFront.

Terraform calls this from the UI local-exec provisioner. The AWS CLI uses
whatever credentials are already in the environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.check_call(args)


def main() -> None:
    ui_dir = Path(os.environ["POTTY_UI_DIR"])
    bucket = os.environ["POTTY_UI_BUCKET"]
    distribution_id = os.environ["POTTY_DISTRIBUTION_ID"]
    if not (ui_dir / "index.html").is_file():
        sys.exit(f"missing {ui_dir / 'index.html'}")

    _run(
        [
            "aws",
            "s3",
            "sync",
            str(ui_dir),
            f"s3://{bucket}",
            "--delete",
            "--region",
            "us-east-1",
            "--only-show-errors",
        ]
    )
    _run(
        [
            "aws",
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            distribution_id,
            "--paths",
            "/*",
        ]
    )


if __name__ == "__main__":
    main()
