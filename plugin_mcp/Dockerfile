FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./backend-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt \
    && pip install --no-cache-dir "mcp>=1.28,<2"

COPY backend ./backend
COPY plugin_mcp ./plugin_mcp

CMD ["sh", "-c", "exec uvicorn plugin_mcp.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
