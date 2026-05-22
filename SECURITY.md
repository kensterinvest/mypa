# Security policy

MyPA stores personal data and connects to third-party services on behalf
of its users. Security issues are taken seriously.

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.** Public
issues are indexed by search engines and notify all watchers
immediately, which is the wrong shape for a coordinated fix.

Instead, email **security@hyson.life** with:

1. A description of the issue (what's exposed, what an attacker can do)
2. Steps to reproduce — minimal repro, not a full PoC if not needed
3. The affected version (git commit SHA or release tag)
4. Whether you've shared the finding with anyone else

You'll get an acknowledgement within **3 working days**. If you don't,
re-send — your first email may have been filtered.

## Response timeline

We aim to:

- Confirm or reject within **7 working days**
- Ship a fix or mitigation within **30 days** for high-severity issues
  (privilege escalation, cross-tenant data exposure, remote code
  execution, authentication bypass)
- Credit you in the release notes unless you ask otherwise

## Scope

In scope:

- The MyPA backend (`mypa/` directory): REST API, MCP server, OAuth
  endpoints, attachment handling, notification dispatch
- The MyPA dashboard (separate repo `kensterinvest/mypa-dashboard`):
  authentication flow, token handling, attachment rendering
- The `setup.sh` installer and `deploy/` templates
- The ntfy server configuration and `mypa/ntfy_admin.py` user lifecycle

Out of scope (report to the upstream project):

- Bugs in third-party dependencies (FastAPI, SQLCipher, ntfy, Caddy,
  Anthropic SDK, etc.)
- Operator-misconfiguration scenarios (e.g. running with a default
  bearer token)
- Anything requiring physical access to the VPS or its disks
- Issues in the user's own Claude.ai connector setup
- Notification content visible to APNs/FCM (documented limitation;
  inherent to iOS/Android push, not MyPA-specific)

## What is NOT considered a vulnerability

- Lack of multi-factor auth on operator login (operator is by definition
  a sysadmin on their own VPS — MFA is a feature, not a security
  boundary)
- Self-hosted deployments where the operator misconfigures Caddy / UFW /
  systemd
- iOS background-delivery latency on self-hosted ntfy (documented
  tradeoff)

## Coordinated disclosure

Standard 90-day coordinated disclosure. If 90 days pass without a fix,
you may disclose publicly. Earlier disclosure (e.g. active exploitation)
is acceptable — email and let us know.

## Supported versions

| Version | Status |
|---|---|
| `main` branch (HEAD) | actively supported |
| latest released tag | actively supported |
| previous tags | best-effort; please upgrade |
