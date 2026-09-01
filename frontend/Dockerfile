# syntax=docker/dockerfile:1

# ============================================================================
# Frontend image (multi-stage)
#
#   deps  -> installed node_modules (cached on package manifests)
#   dev   -> Vite dev server with HMR (source bind-mounted by compose)
#   build -> produces the static production bundle (dist/)
#   prod  -> nginx serving the built static assets
#
# Build a specific stage with:  docker build --target dev  (or --target prod)
# ============================================================================

# ---------------------------------------------------------------------------
# deps: install node_modules. Copying only manifests first keeps this layer
# cached until dependencies actually change.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* .npmrc* ./
RUN npm ci

# ---------------------------------------------------------------------------
# dev: Vite dev server. Binds to 0.0.0.0 so it is reachable from the host, and
# disables auto-open (no browser inside the container). Source is bind-mounted
# by docker-compose; node_modules stays in the image via an anonymous volume.
# ---------------------------------------------------------------------------
FROM deps AS dev
COPY . .
EXPOSE 4300
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--no-open"]

# ---------------------------------------------------------------------------
# build: compile the production bundle into /app/dist.
# VITE_API_URL is a build-time arg because Vite inlines VITE_* vars at build.
# ---------------------------------------------------------------------------
FROM deps AS build
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# prod: serve the static bundle with nginx (SPA history fallback + /api proxy).
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
