FROM python:3.11-slim
WORKDIR /app
COPY hermes_lab/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY hermes_lab /app/hermes_lab
ENV PORT=8080
CMD ["sh", "-c", "uvicorn hermes_lab.runtime_compat:app --host 0.0.0.0 --port ${PORT}"]
