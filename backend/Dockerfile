FROM node:20-alpine AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js vite.runtime.config.js vite.delivery.config.js vite.flowviews.config.js vite.flowviews2.config.js vite.flowviews3.config.js vite.flowviews4.config.js vite.po-list-independent.config.js vite.finance-ui-placement.js ./
COPY tests/assert-po-reminder-actions-build.mjs ./tests/assert-po-reminder-actions-build.mjs
COPY scripts/apply-po-planner-fix.mjs ./scripts/apply-po-planner-fix.mjs
COPY src ./src
COPY public ./public

# Keep the large PO planner source readable in the repo while applying two
# narrowly-scoped production invariants before Vite compiles it:
# 1) recommendation uses current actual dapur stock, not projected depletion;
# 2) Tarik Data also loads saved PO coverage so already-ordered items are known.
RUN node ./scripts/apply-po-planner-fix.mjs

# Build one bundle per accountant database. The Operations/Calculator UI is the
# same in both; only App.jsx accountant runtime defaults differ.
RUN VITE_SITE_ID=sppg-maja-gpt-site \
    VITE_FIRESTORE_DATABASE_ID='(default)' \
    VITE_SITE_LABEL='SPPG MAJA BARU' \
    VITE_SITE_SHORT_LABEL='Maja' \
    npm run build && mv dist dist-maja
RUN VITE_SITE_ID=sppg-cemplang2-gpt-site \
    VITE_FIRESTORE_DATABASE_ID='cemplang2' \
    VITE_SITE_LABEL='SPPG CEMPLANG 2' \
    VITE_SITE_SHORT_LABEL='Cemplang 2' \
    npm run build && mv dist dist-cemplang

# Both bundles use hashed asset names. Merge assets into one static directory
# and preserve the Cemplang index separately.
RUN cp dist-cemplang/index.html dist-maja/index-cemplang.html \
    && cp -r dist-cemplang/assets/. dist-maja/assets/

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY legacy ./legacy
COPY schema ./schema
COPY parser ./parser
COPY workflow ./workflow
COPY --from=frontend /src/dist-maja ./dist
CMD ["sh", "-c", "if [ -n \"${DATABASE_URL:-}\" ]; then python -m backend.migrate || exit 1; else echo 'DATABASE_URL not configured; starting API in degraded mode'; fi; exec uvicorn backend.server:app --host 0.0.0.0 --port ${PORT:-8000}"]