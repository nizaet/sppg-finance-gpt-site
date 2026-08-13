FROM node:20-alpine AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY schema ./schema
COPY parser ./parser
COPY workflow ./workflow
COPY --from=frontend /src/dist ./dist
CMD ["sh", "-c", "if [ -n \"${DATABASE_URL:-}\" ]; then python -m backend.migrate || exit 1; else echo 'DATABASE_URL not configured; starting API in degraded mode'; fi; exec uvicorn backend.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
