# Security policy

MyPA stores personal data — items, decisions, attachments, push
credentials — and connects to third-party services on behalf of its
users. Security issues are taken seriously.

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
- The MyPA dashboard (`mypa-dashboard/` repo): authentication flow,
  JWT/refresh-token handling, attachment rendering
- The `setup.sh` installer and `deploy/` systemd / Caddy templates
- The ntfy server configuration and `mypa/ntfy_admin.py` user lifecycle
- Documented threat-model claims in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)

Out of scope (report to the upstream project):

- Bugs in third-party dependencies (FastAPI, SQLCipher, ntfy, Caddy,
  Anthropic SDK, etc.) — these belong to those projects
- Operator-misconfiguration scenarios (e.g. running with default
  `BEARER_TOKEN_RW=changeme`)
- Anything requiring physical access to the VPS or its disks
- Issues in the user's own Claude.ai connector setup
- Notification content visible to APNs/FCM (documented limitation;
  not a MyPA-specific issue)

## What is NOT considered a vulnerability

- Lack of multi-factor auth on operator login (operator is by definition
  a sysadmin on their own VPS — MFA is a feature, not a security
  boundary)
- Self-hosted deployments where the operator misconfigures Caddy / UFW /
  systemd
- iOS background-delivery latency on self-hosted ntfy (documented
  tradeoff in [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md))

## Coordinated disclosure

We follow standard 90-day coordinated disclosure. If you've reported
to us and 90 days have passed without a fix, you may disclose publicly.
If you need to disclose earlier (e.g. active exploitation), email and
let us know.

## Supported versions

| Version | Status |
|---|---|
| `main` branch (HEAD) | actively supported |
| latest released tag | actively supported |
| previous tags | best-effort; please upgrade |

Pre-`v1.0` there are no LTS branches — users on `main` get the
strongest security posture; users pinned to older revisions should
upgrade or accept the risk.

## Hardening defaults

These are the production defaults documented across this repo. If you
discover a configuration that the docs claim is enabled but isn't, that
is a reportable bug:

- ntfy `auth-default-access: deny-all` — anonymous publish AND subscribe
  both denied
- SQLCipher AES-256 with PBKDF2 256k iterations for the application DB
- OAuth 2.1 with PKCE; DCR redirect-URI allow-list restricted to
  `claude.ai`
- Bearer auth required on all REST + MCP routes except `/health`
- Multi-tenant `user_id` scoping enforced at the service layer (verified
  by `test_multi_tenant.py` and `test_ntfy_account_lifecycle_with_user_mgmt`)
- Attachments served `Content-Disposition: attachment` +
  `X-Content-Type-Options: nosniff`
