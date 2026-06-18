# Irish GTFS Analytics Platform

A production-grade Python application for ingesting, validating, profiling, and analysing Irish public transport GTFS static feed data. Built on a medallion architecture with automated quality monitoring, auto-remediation, a FastAPI REST backend, and a built-in single-page analytics dashboard.

## Architecture

```
GTFS_All.zip (TFI)
       │
       ▼
  Bronze Layer      ← raw data, no transformations, Parquet + metadata
       │
       ▼
 Validation &       ← 39 GTFS-specific rules (CRITICAL / WARNING / INFO)
  Quarantine        ← CRITICAL violations isolated; WARNING records flagged
       │
       ▼
  Silver Layer      ← type-cast, deduplicated, enriched clean data
       │
       ▼
   Gold Layer       ← analytics aggregates (route summary, stop activity, …)
       │
       ▼
   FastAPI + HTML Dashboard   ← served at http://localhost:8000
```

Additional layers run alongside the pipeline:
- **Profiling** — per-column statistics (nulls, cardinality, encoding issues)
- **Remediation** — configurable auto-fixes for quarantined records
- **Monitoring** — quality score trends and drift detection

## Quick Start

### Prerequisites

- Python 3.10+
- Windows / Linux / macOS

### 1 — Clone and create a virtual environment

```bash
git clone <repository-url>
cd gtfs
python -m venv venv
```

Activate the environment:

| Shell | Command |
|-------|---------|
| Windows CMD | `venv\Scripts\activate` |
| PowerShell | `venv\Scripts\Activate.ps1` |
| Linux / macOS | `source venv/bin/activate` |

### 2 — Install dependencies

```bash
pip install -e .[core,api]
```

### 3 — Configure environment

```bash
# Windows CMD / PowerShell
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Edit `.env` if you need to change the port, feed URL, or other settings.  
The defaults work out of the box — no changes are required for a first run.

### 4 — Start the server

**With `make` (Git Bash / WSL / Linux / macOS):**

```bash
make dev      # development — auto-reloads on file changes
make serve    # production  — no reload
```

**Without `make` (Windows CMD / PowerShell):**

```powershell
# Development
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Production
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Override the port by changing `8000` to your preferred value (or set `API_PORT` in `.env`).

Open **http://localhost:8000** — the dashboard loads immediately.

The pipeline runs automatically on a daily schedule. No manual trigger is needed; the first run starts automatically on boot when no data exists.

## Dashboard

A single-page HTML dashboard is served at the root URL. It has four top-level tabs:

| Tab | Content |
|-----|---------|
| **Overview** | KPI cards (routes, stops, operators, quality score), route type chart, top 10 busiest stops, violation summary |
| **Operators** | Routes and trips per agency, operator breakdown table |
| **Routes** | Paginated, sortable route list with inline timetable accordion (outbound/inbound, day-type selector, headway badge) |
| **Data Model** | Three sub-tabs — see below |

### Data Model sub-tabs

| Sub-tab | Content |
|---------|---------|
| **Schema** | GTFS file relationship diagram (ER-style), dataset reference cards with live row counts, Bronze / Silver / Gold pipeline explainer |
| **Data Quality** | Quality score KPIs, violation severity counts, top-15 violations chart, per-file clean% progress bars, ingestion metrics, active alerts |
| **Rules** | Full list of validation rules with severity, source file, cross-file dependencies, and violation counts |

## Data Source

The platform downloads all Irish operator data from a single combined TFI feed:

```
https://www.transportforireland.ie/transitData/Data/GTFS_All.zip
```

This feed includes Dublin Bus, Bus Éireann, Go-Ahead, Luas, Irish Rail, Galway City Transport, and others. The URL is configured via `GTFS_ALL_FEED_URL` in `.env` or `src/config.py`.

## API Endpoints

Navigate to **http://localhost:8000/docs** for the full interactive Swagger UI.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check and pipeline status |
| `GET` | `/routes` | Paginated, searchable, sortable route list |
| `GET` | `/stats/route-summary` | Gold layer route summary |
| `GET` | `/stats/operator-summary` | Per-operator aggregates |
| `GET` | `/stats/headway` | Headway analysis per route/direction |
| `GET` | `/stats/hourly-departures` | Departure counts by hour of day (0–23) |
| `GET` | `/stats/headway-distribution` | Routes bucketed by average headway band |
| `GET` | `/timetable/{route_id}` | Timetable for a route (trips, stops, service days) |
| `GET` | `/validation/summary` | Latest validation report |
| `GET` | `/rules` | All validation rules with metadata |
| `GET` | `/monitoring/latest` | Latest quality metrics |
| `GET` | `/monitoring/alerts` | Active monitoring alerts |
| `GET` | `/monitoring/history` | Quality score history (last 90 runs by default) |
| `GET` | `/pipeline/status` | Current pipeline run status |
| `GET` | `/pipeline/schedule` | Next scheduled run time |

## Makefile Commands

> `make` requires Git Bash, WSL, or a Unix environment. On Windows you can run the underlying commands directly (shown in parentheses).

```bash
make install        # pip install -e .[core,api]
make install-all    # pip install -e .[core,api,dev,...]
make dev            # uvicorn src.api.main:app --reload
make serve          # uvicorn src.api.main:app
make ingest         # python -m src.ingestion.pipeline
make validate       # python -m src.validation.runner
make remediate      # python -m src.remediation.engine
make monitor        # python -m src.monitoring.monitor
make test           # pytest -v --cov=src
make lint           # flake8 + mypy
make format         # black src --line-length 100
make clean          # Remove __pycache__ and pipeline output dirs
```

## Configuration

Copy `.env.example` to `.env` and edit. All settings can also be set as environment variables.

| Setting | Default | Description |
|---------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Bind address |
| `API_PORT` | `8000` | FastAPI port |
| `API_WORKERS` | `1` | Uvicorn workers — keep at 1 unless state is moved to Redis |
| `PIPELINE_ADMIN_TOKEN` | _(empty)_ | If set, `POST /pipeline/run` requires `X-Admin-Token` header |
| `DATABASE_TYPE` | `sqlite` | `sqlite` or `postgresql` |
| `SQLITE_DB_PATH` | `./gtfs.db` | SQLite file location |
| `GTFS_ALL_FEED_URL` | TFI combined zip | Live feed URL |
| `AUTO_REMEDIATE_ENABLED` | `False` | Enable auto-fix on pipeline run |
| `QUALITY_DRIFT_THRESHOLD` | `5.0` | % quality score drop before alert |
| `RECORD_COUNT_DRIFT_THRESHOLD` | `10.0` | % record count change before alert |
| `FEED_STALENESS_DAYS` | `7` | Days until no future service triggers staleness alert |
| `BATCH_SIZE` | `10000` | Rows per processing batch |
| `MAX_WORKERS` | `4` | Thread pool size for parallel pipeline steps |
| `SAMPLE_SIZE` | _(unset)_ | Caps `stop_times`/`shapes` at N rows during ingestion — use on memory-constrained hosts |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Project Structure

```
gtfs/
├── src/
│   ├── config.py              # All settings (paths, thresholds, URL)
│   ├── utils/
│   │   ├── logging.py         # Rotating file + console logger
│   │   ├── file_io.py         # Parquet / CSV / zip helpers
│   │   └── date_utils.py      # GTFS date/time parsing (handles >24h)
│   ├── ingestion/
│   │   ├── bronze.py          # Raw download → Parquet
│   │   ├── silver.py          # Clean & standardise
│   │   ├── gold.py            # Analytics aggregates
│   │   └── pipeline.py        # Orchestrator (entry point)
│   ├── validation/
│   │   ├── rules.py           # 39 ValidationRule subclasses
│   │   └── runner.py          # Runs rules, separates quarantine
│   ├── profiling/
│   │   └── profiler.py        # Per-column statistics → JSON + Parquet
│   ├── remediation/
│   │   └── engine.py          # Auto-fix engine
│   ├── monitoring/
│   │   └── monitor.py         # Quality metrics, drift alerts
│   └── api/
│       ├── main.py            # FastAPI application + pipeline scheduler
│       └── static/
│           └── index.html     # Single-page analytics dashboard
├── outputs/                   # Generated artifacts (git-ignored)
│   ├── bronze/                # Raw partitioned Parquet
│   ├── silver/                # Cleaned Parquet
│   ├── gold/                  # Analytics tables (Parquet + CSV)
│   ├── quarantine/            # Violations + validation summary
│   ├── remediation/           # Remediation log
│   ├── monitoring/            # Quality metrics time-series
│   └── profiles/              # Column statistics
├── tests/
│   ├── conftest.py
│   ├── test_validation_rules.py
│   └── test_validation_runner.py
├── .env.example               # Environment variable template
├── Makefile
└── pyproject.toml
```

## Validation Rules

39 rules across 3 severity levels applied automatically on every pipeline run.

### CRITICAL (records quarantined)
- `STOP-001/002/003/004` — null stop_id, null coordinates, coordinates outside Ireland
- `ROUTE-001/002` — null route_id, agency_id not in agency.txt
- `TRIP-001/002/003` — null trip_id, orphaned route_id, orphaned service_id
- `ST-001/002/003/004` — orphaned trip_id/stop_id, null times, departure before arrival
- `CAL-001/002` — null service_id, start_date after end_date
- `REF-001/002` — agency/route cross-file mismatches

### WARNING (records flagged, not quarantined)
Missing optional names, invalid enumerations, expired services, sequence issues.

### INFO (informational)
Encoding artefacts, single-stop trips, date ranges > 366 days.

### Adding a New Rule

```python
# src/validation/rules.py
@dataclass
class MyNewRule(ValidationRule):
    def __init__(self):
        super().__init__(
            rule_code="XX-001",
            description="description of what fails",
            severity="WARNING",
            source_file="stops.txt",
            required_files=[],
        )

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df["some_col"].isna()]   # return only failing rows
```

Add an instance to `ALL_RULES` at the bottom of `rules.py`. No runner changes needed.

## Running Tests

```bash
make test
# or: pytest tests/ -v --cov=src
```

## Power BI Integration

Gold tables are written as both Parquet and CSV to `outputs/gold/`.

1. Open Power BI Desktop
2. **Get Data → Folder** → point to `outputs/gold/`
3. Connect files individually or combine
4. Suggested visuals: route heatmaps, stop utilisation maps, quality score trends

## Troubleshooting

**Dashboard shows "No pipeline data found"**
The pipeline runs on startup if no data exists. Wait for it to complete, or run `make ingest` manually.

**Pipeline fails with network error**
The platform falls back to built-in sample data automatically. Check `logs/gtfs.log` for details.

**API returns empty arrays**
Run `make ingest` to populate `outputs/gold/`.

**Memory errors with large feeds / deploying on Render's free tier (512Mi)**
The combined TFI feed covers every Irish operator, so `stop_times` and `shapes` can run into the millions of rows. If the pipeline OOMs during the first boot run, set `SAMPLE_SIZE` (e.g. `SAMPLE_SIZE=300000`) as an environment variable — it caps `stop_times`/`shapes` at that many rows during ingestion while keeping all other GTFS files complete, so routes/stops/operators stay accurate, just with fewer scheduled trips. Unset it (or raise it) once you've moved to a host with more memory.

**Multiple workers cause inconsistent state**
Keep `API_WORKERS=1`. Pipeline status and the Silver cache are in-process; multiple workers give independent copies. Move state to Redis before scaling workers.
