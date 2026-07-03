# ============================================================
#  GEM Tender Intelligence — Backend Dockerfile
#  Production-grade multi-stage build with:
#    - Python 3.12 (stable, compatible with all deps)
#    - OCR (Tesseract + Poppler)
#    - PDF processing (pdfplumber)
#    - ML/AI (scikit-learn, numpy)
#    - Non-root security
# ============================================================

# ── Stage 1: Build ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    libpq-dev \
    python3-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/gemuser/.local/bin:$PATH \
    PYTHONPATH=/app

# Runtime system dependencies: OCR + PDF + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR engine
    tesseract-ocr \
    tesseract-ocr-hin \
    tesseract-ocr-eng \
    # PDF rendering (pdfplumber, pdf2image)
    poppler-utils \
    libpoppler-dev \
    # Network utils
    curl wget \
    # Image processing (PIL/Pillow)
    libjpeg-dev libpng-dev libwebp-dev \
    # Fonts for PDF generation
    fonts-liberation fonts-noto \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local /usr/local

# Create non-root user
RUN adduser --disabled-password --gecos '' --uid 1001 gemuser && \
    mkdir -p /app/uploads /app/rag_index /app/contracts /app/llm_cache && \
    chown -R gemuser:gemuser /app

# Copy application code
COPY --chown=gemuser:gemuser . .

USER gemuser

# Health check
HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Production: Gunicorn with Uvicorn workers
# Development override: uvicorn main:app --reload
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "h11"]
