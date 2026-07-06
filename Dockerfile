# Single-image deployment for ProdAgent: FastAPI backend + Next.js frontend.

FROM node:20-bookworm-slim AS frontend-deps
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app/frontend
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ARG NEXT_PUBLIC_SCRIPT_ID=690c1b6736c9c50c40160976
ARG NEXT_PUBLIC_USER_ID=dev_user_frontend
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_SCRIPT_ID=$NEXT_PUBLIC_SCRIPT_ID
ENV NEXT_PUBLIC_USER_ID=$NEXT_PUBLIC_USER_ID
COPY --from=frontend-deps /app/frontend/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    BACKEND_PORT=8000 \
    FRONTEND_PORT=3000

WORKDIR /app

# Avoid apt-get in the runtime image: some deployment networks cannot resolve
# deb.debian.org during build. Reuse the Node runtime from the frontend stage.
COPY --from=frontend-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-deps /usr/local/bin/npm /usr/local/bin/npm
COPY --from=frontend-deps /usr/local/bin/npx /usr/local/bin/npx
COPY --from=frontend-deps /usr/local/lib/node_modules /usr/local/lib/node_modules

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/app /app/backend/app
COPY backend/pytest.ini /app/backend/pytest.ini
COPY frontend/package*.json /app/frontend/
COPY --from=frontend-deps /app/frontend/node_modules /app/frontend/node_modules
COPY --from=frontend-build /app/frontend/.next /app/frontend/.next
COPY --from=frontend-build /app/frontend/public /app/frontend/public
COPY --from=frontend-build /app/frontend/next.config.js /app/frontend/next.config.js
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh && mkdir -p /app/backend/logs

EXPOSE 8000 3000
CMD ["/app/entrypoint.sh"]
