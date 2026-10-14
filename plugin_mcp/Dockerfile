FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./backend-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt \
    && pip install --no-cache-dir "mcp>=1.28,<2" "sse-starlette==2.4.0" "starlette==0.47.3" "PyJWT[crypto]>=2.9,<3" "httpx>=0.27,<1" "python-multipart>=0.0.9,<1"

COPY backend ./backend
COPY parser ./parser
COPY schema ./schema
COPY legacy ./legacy
COPY workflow ./workflow
COPY plugin_mcp ./plugin_mcp

CMD ["sh", "-c", "exec uvicorn plugin_mcp.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
