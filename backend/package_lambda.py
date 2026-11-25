"""Build the Lambda zip source for Terraform.

Installs Linux wheels into infra/terraform/build/lambda and copies potty_train
next to them. boto3 is provided by the Lambda runtime and is not installed.
Run this from any directory before terraform apply:

    python backend/package_lambda.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "infra" / "terraform" / "build" / "lambda"
REQUIREMENTS = ROOT / "backend" / "requirements-lambda.txt"
PACKAGE = ROOT / "backend" / "potty_train"


# Wheels for the Lambda runtime. http-ece publishes source only; it is pure
# Python, so it is installed afterwards without a platform tag.
_LINUX = [
    "--platform",
    "manylinux2014_x86_64",
    "--implementation",
    "cp",
    "--python-version",
    "3.12",
    "--abi",
    "cp312",
    "--only-binary=:all:",
]


def _pip(*args: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(DEST), *args])


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    _pip("--no-deps", *_LINUX, "--requirement", str(REQUIREMENTS))
    _pip(
        *_LINUX,
        "aiohttp",
        "cryptography>=47",
        "requests>=2.21",
        "py-vapid>=1.7",
    )
    _pip("--no-deps", "http-ece>=1.1.0")
    shutil.copytree(
        PACKAGE,
        DEST / "potty_train",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


if __name__ == "__main__":
    main()
