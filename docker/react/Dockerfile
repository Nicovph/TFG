# syntax=docker/dockerfile:1
# Build the non-root Vite development image used by the local MVP stack.
FROM node:24.19.0-bookworm-slim

# Keep the application in a dedicated directory owned by the unprivileged user
# provided by the official Node.js image.
WORKDIR /app
RUN chown node:node /app
USER node

# Install the exact dependency graph before copying the source to preserve the
# dependency layer when only application files change. The BuildKit cache keeps
# downloaded npm artifacts between builds without adding them to the image;
# numeric ownership lets the unprivileged node user write to the cache safely.
COPY --chown=node:node frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
    npm ci --no-audit --no-fund

COPY --chown=node:node frontend/ ./

# Documents the Vite development port; Compose controls host publication.
EXPOSE 5173

# Listen on the container interface and fail instead of silently selecting a
# different port, which keeps the Compose healthcheck deterministic.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--strictPort"]
