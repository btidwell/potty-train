"""Build Lambda zip sources for Terraform.

Builds three packages under infra/terraform/build/:

- lambda/     main API (potty_train)
- mcp/        MCP tool server (potty_mcp + potty_train)
- agent/      Strands chat agent (potty_agent + deps + LWA run.sh)

boto3 is provided by the Lambda runtime and is not installed.
Run this from any directory before terraform apply:

    python backend/package_lambda.py
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "infra" / "terraform" / "build"
API_DEST = BUILD / "lambda"
MCP_DEST = BUILD / "mcp"
AGENT_DEST = BUILD / "agent"
API_REQUIREMENTS = ROOT / "backend" / "requirements-lambda.txt"
MCP_REQUIREMENTS = ROOT / "backend" / "requirements-mcp.txt"
AGENT_REQUIREMENTS = ROOT / "backend" / "requirements-agent.txt"
PACKAGE = ROOT / "backend" / "potty_train"
MCP_PACKAGE = ROOT / "backend" / "potty_mcp"
AGENT_PACKAGE = ROOT / "backend" / "potty_agent"


# Wheels for the Lambda runtime. http-ece publishes source only; it is pure
# Python, so it is installed afterwards without a platform tag.
# Pip still evaluates environment markers with the host interpreter. This
# machine is newer than Lambda's Python 3.12, so packages that require
# typing_extensions only on 3.12 (aiohttp, aiosignal) would otherwise be
# installed without it.
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


def _pip(dest: Path, *args: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(dest), *args])


def _copy_package(src: Path, dest: Path) -> None:
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _install_api_deps(dest: Path) -> None:
    """Deps potty_train needs for push, JWT, and PDF (API, MCP tools, agent)."""
    _pip(dest, "--no-deps", *_LINUX, "--requirement", str(API_REQUIREMENTS))
    _pip(
        dest,
        *_LINUX,
        "aiohttp",
        "cryptography>=47",
        "requests>=2.21",
        "py-vapid>=1.7",
        "typing_extensions>=4.4",
    )
    _pip(dest, "--no-deps", "http-ece>=1.1.0")


def _build_api() -> None:
    if API_DEST.exists():
        shutil.rmtree(API_DEST)
    API_DEST.mkdir(parents=True)
    _install_api_deps(API_DEST)
    _copy_package(PACKAGE, API_DEST / "potty_train")


def _build_mcp() -> None:
    if MCP_DEST.exists():
        shutil.rmtree(MCP_DEST)
    MCP_DEST.mkdir(parents=True)
    try:
        _pip(MCP_DEST, *_LINUX, "--requirement", str(MCP_REQUIREMENTS))
    except subprocess.CalledProcessError:
        _pip(MCP_DEST, "--requirement", str(MCP_REQUIREMENTS))
    _install_api_deps(MCP_DEST)
    _copy_package(PACKAGE, MCP_DEST / "potty_train")
    _copy_package(MCP_PACKAGE, MCP_DEST / "potty_mcp")


def _build_agent() -> None:
    if AGENT_DEST.exists():
        shutil.rmtree(AGENT_DEST)
    AGENT_DEST.mkdir(parents=True)
    # Strands and friends publish manylinux wheels for most deps; install with
    # the Linux tag when possible, then fill gaps without the platform pin.
    # Do not install API push/PDF deps here: the direct Lambda upload limit is
    # ~70MB, and pywebpush/fonttools push the agent zip over that. Chat auth
    # only needs PyJWT (in requirements-agent); service loads push lazily.
    try:
        _pip(AGENT_DEST, *_LINUX, "--requirement", str(AGENT_REQUIREMENTS))
    except subprocess.CalledProcessError:
        _pip(AGENT_DEST, "--requirement", str(AGENT_REQUIREMENTS))
    _copy_package(PACKAGE, AGENT_DEST / "potty_train")
    _copy_package(MCP_PACKAGE, AGENT_DEST / "potty_mcp")
    _copy_package(AGENT_PACKAGE, AGENT_DEST / "potty_agent")
    run_sh = AGENT_DEST / "run.sh"
    shutil.copy2(AGENT_PACKAGE / "run.sh", run_sh)
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)



def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    _build_api()
    _build_mcp()
    _build_agent()


if __name__ == "__main__":
    main()
