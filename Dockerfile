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

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

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
