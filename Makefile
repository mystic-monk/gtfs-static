.PHONY: help install install-all clean ingest serve dashboard validate remediate monitor test lint format

help:
	@echo "Irish GTFS Analytics Platform - Available Commands"
	@echo "=================================================="
	@echo "make install          - Install core dependencies"
	@echo "make install-all      - Install all dependencies (core, api, dashboard, etl, validation, remediation, monitoring, dev)"
	@echo "make clean            - Remove cache and output directories"
	@echo "make ingest           - Run the full ingestion pipeline (Bronze -> Quarantine -> Silver -> Gold -> Profiles)"
	@echo "make serve            - Start the FastAPI backend server (port 8000)"
	@echo "make dashboard        - Start the Streamlit dashboard (port 8501)"
	@echo "make validate         - Run validation rule engine and display report"
	@echo "make remediate        - Run automated remediation engine"
	@echo "make monitor          - Run monitoring and alerting layer"
	@echo "make test             - Run unit tests with coverage"
	@echo "make lint             - Run code quality checks (flake8, mypy)"
	@echo "make format           - Format code with black"

install:
	pip install -e .[core,etl]

install-all:
	pip install -e .[core,api,dashboard,etl,validation,remediation,monitoring,dev]

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf outputs/bronze outputs/silver outputs/quarantine outputs/remediation outputs/monitoring 2>/dev/null || true
	echo "Cleaned cache and output directories"

ingest:
	python -m src.ingestion.pipeline

serve:
	python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

dashboard:
	streamlit run src/dashboard/app.py

validate:
	python -m src.validation.runner

remediate:
	python -m src.remediation.engine

monitor:
	python -m src.monitoring.monitor

test:
	pytest -v --cov=src --cov-report=html --cov-report=term-missing

lint:
	flake8 src tests --count --statistics --show-source --max-line-length=100
	mypy src --ignore-missing-imports

format:
	black src tests --line-length 100

.DEFAULT_GOAL := help
