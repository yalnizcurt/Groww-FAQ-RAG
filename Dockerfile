# Stage 1: Build the React frontend
FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --frozen-lockfile --legacy-peer-deps || npm install --legacy-peer-deps
COPY frontend/ ./
# Ensure production API URL is relative to the same host
ENV REACT_APP_BACKEND_URL=""
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for Playwright and ML libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its browser dependencies
RUN playwright install --with-deps chromium

# Copy backend code
COPY backend/ ./backend

# Copy built frontend assets to the expected path relative to ROOT_DIR
COPY --from=frontend-builder /app/frontend/build /app/frontend/build

# Expose port (Cloud Run uses PORT env var, defaults to 8080)
ENV PORT=8080
EXPOSE 8080

# Pre-download ML models to bake them into the image (speed up first request)
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
RUN python3 -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# ---------------------------------------------------------------------------
# Build-time corpus ingestion.
# backend/data/ is gitignored so we must build the index here so the
# container ships with real data. Cloud Build / CI passes GROQ_API_KEY as
# a --build-arg; it is NOT baked into the final layer (only used to run
# the ingest script which writes to the data/index/ folder on disk).
# ---------------------------------------------------------------------------
WORKDIR /app/backend
RUN python3 -c "
from mf_faq.ingestion.pipeline import refresh
import json, sys, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
res = refresh(force=True, skip_fetch=False)
print(json.dumps(res.to_dict(), indent=2, default=str))
if res.outcome not in ('ok', 'partial'):
    print('WARNING: ingestion outcome =', res.outcome, '— container will start without index.')
    print('Use /api/reingest after deployment to rebuild.')
"

# Start the server
CMD uvicorn server:app --host 0.0.0.0 --port $PORT
