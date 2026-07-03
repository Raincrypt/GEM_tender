# ============================================================
#  GEM Tender Procurement Ecosystem — Developer Makefile
#  Usage: make <target>
# ============================================================

.PHONY: help dev seed seed-rag test clean docker-up docker-down docker-build \
        docker-logs reset-db backup-db lint format install check-health \
        db-migrate db-upgrade db-stamp

BACKEND_DIR = backend
PYTHON      = python
PIP         = pip
UVICORN     = uvicorn

# Default target
help:
	@echo ""
	@echo "  GEM Tender Procurement Ecosystem — Make Commands"
	@echo "  =================================================="
	@echo ""
	@echo "  Development"
	@echo "    make dev          Start the FastAPI dev server (hot-reload)"
	@echo "    make install      Install all Python dependencies"
	@echo "    make seed         Seed the database with IOCL demo data"
	@echo "    make seed-rag     Seed the RAG vector index"
	@echo "    make reset-db     Reset and re-create the database (DESTRUCTIVE)"
	@echo "    make backup-db    Backup the SQLite database"
	@echo ""
	@echo "  Database Migrations (Alembic)"
	@echo "    make db-migrate m=\"...\" Generate a new schema migration (autogenerate)"
	@echo "    make db-upgrade   Upgrade database to latest migration head"
	@echo "    make db-stamp     Stamp database to latest migration head without running migrations"
	@echo ""
	@echo "  Docker"
	@echo "    make docker-up    Start all services (build if needed)"
	@echo "    make docker-down  Stop all services"
	@echo "    make docker-build Rebuild all Docker images"
	@echo "    make docker-logs  Tail logs from all containers"
	@echo ""
	@echo "  Quality"
	@echo "    make test         Run all tests"
	@echo "    make lint         Run ruff linter"
	@echo "    make format       Format code with ruff"
	@echo "    make check-health Check API health endpoint"
	@echo ""
	@echo "  Maintenance"
	@echo "    make clean        Remove __pycache__ and temp files"
	@echo ""

# ── Development ─────────────────────────────────────────────
dev:
	@echo "Starting GEM Tender API with hot-reload..."
	cd $(BACKEND_DIR) && $(UVICORN) main:app --reload --host 0.0.0.0 --port 8000 --log-level info

install:
	@echo "Installing Python dependencies..."
	cd $(BACKEND_DIR) && $(PIP) install -r requirements.txt

seed:
	@echo "Seeding IOCL demo data..."
	cd $(BACKEND_DIR) && $(PYTHON) seed_iocl.py

seed-rag:
	@echo "Seeding RAG vector index..."
	cd $(BACKEND_DIR) && $(PYTHON) seed_rag.py

reset-db:
	@echo "WARNING: This will DELETE all data. Press Ctrl+C to cancel..."
	@sleep 3
	cd $(BACKEND_DIR) && $(PYTHON) reset_db.py
	@echo "Database reset complete. Run 'make seed' to re-populate."

backup-db:
	@echo "Backing up SQLite database..."
	@mkdir -p backups
	@copy backend\gem_tender.db backups\gem_tender_$(shell date +%Y%m%d_%H%M%S).db 2>/dev/null || \
	 cp backend/gem_tender.db backups/gem_tender_$$(date +%Y%m%d_%H%M%S).db
	@echo "Backup created in ./backups/"

# ── Database Migrations (Alembic) ───────────────────────────
db-migrate:
	@echo "Generating new database migration..."
	cd $(BACKEND_DIR) && $(PYTHON) -m alembic revision --autogenerate -m "$(m)"

db-upgrade:
	@echo "Applying database migrations..."
	cd $(BACKEND_DIR) && $(PYTHON) -m alembic upgrade head

db-stamp:
	@echo "Stamping database to latest migration head..."
	cd $(BACKEND_DIR) && $(PYTHON) -m alembic stamp head

# ── Docker ──────────────────────────────────────────────────
docker-up:
	@echo "Starting Docker stack..."
	docker compose up -d --build
	@echo "Services running. Frontend: http://localhost | API: http://localhost:8000/docs"

docker-down:
	@echo "Stopping Docker stack..."
	docker compose down

docker-build:
	@echo "Rebuilding Docker images (no cache)..."
	docker compose build --no-cache

docker-logs:
	docker compose logs -f

# ── Quality Assurance ────────────────────────────────────────
test:
	@echo "Running tests..."
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest test_all_endpoints.py -v

lint:
	@echo "Running ruff linter..."
	cd $(BACKEND_DIR) && ruff check .

format:
	@echo "Formatting code with ruff..."
	cd $(BACKEND_DIR) && ruff format .

check-health:
	@echo "Checking API health..."
	curl -s http://localhost:8000/health | python -m json.tool

# ── Maintenance ──────────────────────────────────────────────
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
