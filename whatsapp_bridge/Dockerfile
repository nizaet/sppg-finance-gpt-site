FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY whatsapp_bridge/package*.json ./
RUN npm ci --omit=dev
COPY whatsapp_bridge/ ./
RUN npm test
ENV NODE_ENV=production DATA_DIR=/data PORT=8080
EXPOSE 8080
CMD ["node","server.mjs"]
