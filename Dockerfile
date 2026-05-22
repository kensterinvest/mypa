# =============================================================
# MyPA backend image — runs mypa-api OR mypa-mcp depending on the
# CMD passed by docker-compose. Single image, two services.
# =============================================================

FROM python:3.12-slim AS base

# System packages: SQLCipher dev headers (for sqlcipher3-binary
# build-from-source fallback), sudo (for ntfy_admin.py shelling out
# to the ntfy CLI), curl + ca-certs for health checks and dependency
# downloads.
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlcipher libsqlcipher-dev libssl-dev libffi-dev \
        sudo curl ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged user matching the bare-metal install conventions.
RUN useradd --system --create-home --home-dir /var/lib/mypa \
        --shell /usr/sbin/nologin mypa

WORKDIR /opt/mypa

# Python deps — pinned versions match what setup.sh installs.
COPY --chown=mypa:mypa requirements.docker.txt /opt/mypa/requirements.docker.txt
RUN pip install --no-cache-dir -r requirements.docker.txt

# Source. .dockerignore at repo root keeps this slim.
COPY --chown=mypa:mypa . /opt/mypa/

# Prepare runtime dirs (volumes will mount over these at runtime).
RUN install -d -o mypa -g mypa -m 0750 \
        /var/lib/mypa /var/lib/mypa/blobs \
        /var/log/mypa /etc/mypa

# entrypoint applies migrations + bootstraps the admin user on first run.
COPY --chown=root:root docker/entrypoint.sh /usr/local/bin/mypa-entrypoint
RUN chmod 0755 /usr/local/bin/mypa-entrypoint

# ntfy CLI is needed by mypa.ntfy_admin (sudo-shells out to it). The
# CLI is fetched from the ntfy .deb release at image build.
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://github.com/binwiederhier/ntfy/releases/download/v2.11.0/ntfy_2.11.0_linux_${ARCH}.deb" -o /tmp/ntfy.deb \
    && dpkg -i /tmp/ntfy.deb \
    && rm /tmp/ntfy.deb

# Sudoers — the same narrow allow-list setup.sh installs on bare metal.
# Required so mypa user can run `ntfy user add` / `access` / `change-pass`
# without a password.
RUN echo 'mypa ALL=(root) NOPASSWD: SETENV: /usr/bin/ntfy user add *, /usr/bin/ntfy user remove *, /usr/bin/ntfy user change-pass *, /usr/bin/ntfy access *, /usr/bin/ntfy token *' \
        > /etc/sudoers.d/mypa-ntfy \
    && chmod 0440 /etc/sudoers.d/mypa-ntfy

USER mypa

ENV PYTHONPATH=/opt/mypa
ENV PYTHONUNBUFFERED=1

EXPOSE 8022 8023

ENTRYPOINT ["/usr/local/bin/mypa-entrypoint"]
# Default to the API; docker-compose overrides for mypa-mcp.
CMD ["api"]
