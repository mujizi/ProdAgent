# Single-image deployment for ProdAgent: FastAPI backend + Next.js frontend.

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app/frontend
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ARG NEXT_PUBLIC_SCRIPT_ID=6a4f56a54bc764f6d3181d83
ARG NEXT_PUBLIC_USER_ID=dev_user_frontend
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_SCRIPT_ID=$NEXT_PUBLIC_SCRIPT_ID
ENV NEXT_PUBLIC_USER_ID=$NEXT_PUBLIC_USER_ID
COPY frontend/package*.json ./
RUN npm config set registry "$NPM_REGISTRY" \
    && npm config set fetch-retries 5 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm ci --include=dev --no-audit --no-fund --loglevel=warn \
    && test -f node_modules/next/dist/bin/next
COPY frontend/ ./
RUN node node_modules/next/dist/bin/next build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    BACKEND_PORT=8000 \
    FRONTEND_PORT=3000

WORKDIR /app

# Avoid apt-get in the runtime image: some deployment networks cannot resolve
# deb.debian.org during build. Reuse the Node runtime from the frontend stage.
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /usr/local/bin/npm /usr/local/bin/npm
COPY --from=frontend-build /usr/local/bin/npx /usr/local/bin/npx
COPY --from=frontend-build /usr/local/lib/node_modules /usr/local/lib/node_modules

COPY backend/requirements.txt /app/backend/requirements.txt
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r /app/backend/requirements.txt

COPY backend/app /app/backend/app
COPY backend/pytest.ini /app/backend/pytest.ini
COPY frontend/package*.json /app/frontend/
COPY --from=frontend-build /app/frontend/node_modules /app/frontend/node_modules
COPY --from=frontend-build /app/frontend/.next /app/frontend/.next
COPY --from=frontend-build /app/frontend/public /app/frontend/public
COPY --from=frontend-build /app/frontend/next.config.js /app/frontend/next.config.js
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh && mkdir -p /app/backend/logs

EXPOSE 8000 3000
CMD ["/app/entrypoint.sh"]
