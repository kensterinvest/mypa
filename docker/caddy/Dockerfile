# =============================================================
# Caddy image with the MyPA landing site + dashboard SPA baked in.
#
# Multi-stage:
#   1. node — clones kensterinvest/mypa-dashboard at the requested
#      ref, runs `npm ci && npm run build -- --base-href=/app/`
#   2. caddy — final image, copies the dashboard build + site/ into
#      /var/www and ships with a templated Caddyfile.
# =============================================================

ARG DASHBOARD_REPO=https://github.com/kensterinvest/mypa-dashboard.git
ARG DASHBOARD_REF=main

# ----- Stage 1: build the Angular dashboard -----
FROM node:20-alpine AS dashboard-builder
ARG DASHBOARD_REPO
ARG DASHBOARD_REF
RUN apk add --no-cache git
WORKDIR /build
RUN git clone --depth=1 --branch "$DASHBOARD_REF" "$DASHBOARD_REPO" dashboard
WORKDIR /build/dashboard
RUN npm ci --no-audit --no-fund
RUN npm run build -- --base-href=/app/

# ----- Stage 2: Caddy with site + dashboard -----
FROM caddy:2-alpine

# Static landing site
COPY site/ /var/www/mypa-site/

# Built dashboard SPA from stage 1
COPY --from=dashboard-builder /build/dashboard/dist/mypa-dashboard/browser/ /var/www/mypa-dashboard/

# Caddyfile (uses $PUBLIC_HOST + $NTFY_HOST env-var substitution)
COPY docker/caddy/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443
