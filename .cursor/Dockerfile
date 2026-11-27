# Cloud agent base image. Cursor checks out the repo itself; do not COPY the project.
# Python 3.12 matches the Lambda runtime. Node 22 matches Angular 21.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        sudo \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'

# Angular 21 needs Node ^20.19 || ^22.12 || >=24.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource.sh \
    && bash /tmp/nodesource.sh \
    && apt-get install -y nodejs \
    && rm -f /tmp/nodesource.sh \
    && rm -rf /var/lib/apt/lists/* \
    && node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (!((major === 22 && minor >= 12) || major >= 24)) process.exit(1)"

# Cursor cloud agents run as ubuntu and expect passwordless sudo.
RUN id -u ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu \
    && usermod -aG sudo ubuntu \
    && echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu
