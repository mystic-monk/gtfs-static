.PHONY: help install install-all dev serve clean ingest validate remediate monitor test lint format

# ── Overridable defaults (override via env: PORT=9000 make dev) ────────────
PORT    ?= 8000
WORKERS ?= 1
HOST    ?= 0.0.0.0

help:
	@echo ""
	@echo "  Irish GTFS Analytics Platform"
	@echo "  =============================="
	@echo ""
	@echo "  Setup"
	@echo "    make install       Install core + API dependencies"
	@echo "    make install-all   Install every optional dependency group"
	@echo ""
	@echo "  Running the app"
	@echo "    make dev           Start API with --reload (development only)"
	@echo "    make serve         Start API without --reload (production)"
	@echo "    Override port/workers:  PORT=9000 WORKERS=4 make serve"
	@echo ""
	@echo "  Pipeline"
	@echo "    make ingest        Run the full ingestion pipeline"
	@echo "    make validate      Run validation rule engine"
	@echo "    make remediate     Run automated remediation engine"
	@echo "    make monitor       Run monitoring and alerting layer"
	@echo ""
	@echo "  Code quality"
	@echo "    make test          Run tests with coverage"
	@echo "    make lint          flake8 + mypy"
	@echo "    make format        Format code with black"
	@echo ""
	@echo "    make clean         Remove __pycache__ and pipeline output dirs"
	@echo ""

# ── Dependencies ────────────────────────────────────────────────────────────
install:
	pip install -e .[core,api]

install-all:
	pip install -e .[core,api,dashboard,etl,validation,remediation,monitoring,dev]

# ── Running the app ─────────────────────────────────────────────────────────

# Development — auto-reload on file changes; single worker only (reload + multiple workers = broken)
dev:
	python -m uvicorn src.api.main:app --host $(HOST) --port $(PORT) --reload

# Production — no reload; set WORKERS > 1 only if you understand the in-process cache limitation
# (pipeline state and silver cache are per-process; multiple workers give independent copies)
serve:
	python -m uvicorn src.api.main:app --host $(HOST) --port $(PORT) --workers $(WORKERS)

# ── Pipeline steps ───────────────────────────────────────────────────────────
ingest:
	python -m src.ingestion.pipeline

validate:
	python -m src.validation.runner

remediate:
	python -m src.remediation.engine

monitor:
	python -m src.monitoring.monitor

# ── Code quality ─────────────────────────────────────────────────────────────
test:
	pytest -v --cov=src --cov-report=html --cov-report=term-missing

lint:
	flake8 src --count --statistics --show-source --max-line-length=100
	mypy src --ignore-missing-imports

format:
	black src --line-length 100

# ── Maintenance ──────────────────────────────────────────────────────────────
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
	rm -rf outputs/bronze outputs/silver outputs/quarantine outputs/remediation outputs/monitoring 2>/dev/null || true
	@echo "Cleaned."

.DEFAULT_GOAL := help
