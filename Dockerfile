# CashPilot frontend — TanStack Start (Vite + Nitro SSR), built as a
# standalone Node server. See docker-compose.yml for how this pairs with
# backend/Dockerfile.
#
# Why Node instead of static nginx: this app renders its route shell
# server-side per request (see src/routes/__root.tsx) — the client build has
# no root index.html to fall back to. Nitro's "node" preset (selected below
# via NITRO_PRESET, leaving the default Vercel build target untouched) turns
# the exact same `vite build` into a small, self-contained Node HTTP server
# that serves both the SSR shell and the static /screens/*.html pages/assets
# from one process, so direct navigation and refresh on every route work
# exactly as they do in the existing Vercel deployment.

FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN NITRO_PRESET=node npm run build

FROM node:20-slim

WORKDIR /app

COPY --from=builder /app/.output ./

ENV PORT=3000
ENV HOST=0.0.0.0
EXPOSE 3000

CMD ["node", "server/index.mjs"]
