# syntax=docker/dockerfile:1.7
FROM node:22-slim AS builder

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /repo

# Copy only what's needed to install deps first for better caching.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* turbo.json ./
COPY apps/console/package.json ./apps/console/
COPY packages/ui/package.json ./packages/ui/
COPY packages/client-ts/package.json ./packages/client-ts/

RUN pnpm install --no-frozen-lockfile

# Now copy sources and build.
COPY apps/console ./apps/console
COPY packages/ui ./packages/ui
COPY packages/client-ts ./packages/client-ts

RUN pnpm --filter console build

FROM node:22-slim AS runtime

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /app

COPY --from=builder /repo /repo

WORKDIR /repo/apps/console

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=5173

EXPOSE 5173

CMD ["node", "build/index.js"]
