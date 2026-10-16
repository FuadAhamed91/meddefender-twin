# syntax=docker/dockerfile:1
# MedDefender Twin web console: the Vite build served by nginx, which also proxies /api and
# /ws to the backend so the browser sees a single origin (cookies, CSRF and the WebSocket
# Origin check all rely on that).

FROM node:24-slim AS build
WORKDIR /srv/frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Type-checks, then builds (see package.json "build").
RUN npm run build

FROM nginx:1.30-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /srv/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=6 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
