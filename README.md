# Irish GTFS Analytics Platform

A production-grade, modular Python application for ingesting, validating, profiling, and analyzing Irish public transport GTFS static feed data. Built on a medallion architecture with automated quality monitoring, auto-remediation, a FastAPI REST backend, and a Streamlit analytics dashboard.

## Framework Overview

This platform uses **two frameworks** for two different purposes:

| Framework | Role | Default Port |
|-----------|------|-------------|
| **FastAPI** | REST API — exposes analytics data and pipeline triggers as JSON endpoints | `8000` |
| **Streamlit** | Interactive dashboard — visualizes Gold layer tables, quality reports, and monitoring metrics | `8501` |

Both run as independent processes and can be used together or separately.

## Architecture

The platform implements an extended medallion architecture:

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
  ┌────┴────┐
  ▼         ▼
FastAPI   Streamlit
  API    Dashboard
```

Additional layers run alongside the pipeline:
- **Profiling** — per-column statistics (nulls, cardinality, encoding issues)
- **Remediation** — configurable auto-fixes for quarantined records
- **Monitoring** — quality score trends and drift detection

## Quick Start

### Option A — Docker (recommended, no local Python needed)

```bash
git clone <repository-url>
cd gtfs-analytics-platform

# Build and start
docker compose up --build

# Open browser
# http://localhost:8000        → Dashboard (Overview, Routes, Validation, Rules, Pipeline)
# http://localhost:8000/docs   → Swagger API
```

Pipeline outputs (parquet, CSV, profiles) are stored in named Docker volumes and survive container restarts.

To run the pipeline without the browser, use the **Pipeline** tab in the dashboard and click **Run Pipeline**.

### Option B — Local Python

#### Prerequisites

- Python 3.10+
- Windows / Linux / macOS

#### Installation

```bash
git clone <repository-url>
cd gtfs-analytics-platform

# Create and activate virtualenv
python -m venv venv
venv\Scripts\activate       # Windows CMD
# venv\Scripts\Activate.ps1  # PowerShell
# source venv/bin/activate    # Linux / macOS

# Install all dependencies
pip install -e ".[core,api,remediation]"
```

#### Running the Platform

**Start the FastAPI server** (includes the built-in dashboard):
```bash
python -m src.api.main
# http://localhost:8000       → Dashboard
# http://localhost:8000/docs  → Swagger UI
# http://localhost:8000/health
```

Then open the browser, go to the **Pipeline** tab and click **Run Pipeline**. The pipeline downloads live GTFS data and runs all layers. Live log messages stream directly into the browser — no terminal needed.

## Data Source

The platform downloads all Irish operator data from a single combined TFI feed:

```
https://www.transportforireland.ie/transitData/Data/GTFS_All.zip
```

This feed includes Dublin Bus, Bus Éireann, Go-Ahead, Luas, Irish Rail, Galway City Transport, and others. The URL is configured in `src/config.py` as `GTFS_ALL_FEED_URL`. If the live feed is unavailable, the pipeline falls back to built-in sample data automatically.

## FastAPI Endpoints

Navigate to **http://localhost:8000/docs** for the full interactive Swagger UI.

### Core
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Redirects to `/docs` |
| `GET` | `/health` | Health check |
| `GET` | `/operators` | List operators in the feed |
| `GET` | `/routes` | Paginated route list |
| `GET` | `/validation/summary` | Latest validation report |
| `GET` | `/export/{table_name}` | Download a Gold table as CSV |

### Analytics
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/analytics/routes/summary` | Route performance aggregates |
| `GET` | `/analytics/stops/activity` | Stop utilisation metrics |
| `GET` | `/analytics/temporal/patterns` | Hourly / daily trip patterns |
| `GET` | `/analytics/operators/performance` | Per-operator quality scores |

## Streamlit Dashboard Pages

| Page | Content |
|------|---------|
| **1 — Overview** | Key metrics, route type distribution, top busiest stops |
| **2 — Quality** | Violation counts, rule performance, severity breakdowns |
| **3 — Remediation** | Auto-fix statistics, manual quarantine review, bulk actions |
| **4 — Monitoring** | Quality score trends, alert history, drift detection |
| **5 — Explorer** | Interactive table browser, column statistics, export tools |

Dashboard pages cache data for 5 minutes (`@st.cache_data(ttl=300)`) to avoid re-reading Parquet files on every interaction.

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
│   ├── api/
│   │   └── main.py            # FastAPI application
│   └── dashboard/
│       ├── app.py             # Streamlit entry point
│       └── pages/             # 5 dashboard pages
├── outputs/                   # Generated artifacts
│   ├── bronze/                # Raw partitioned Parquet
│   ├── silver/                # Cleaned Parquet
│   ├── gold/                  # Analytics tables (Parquet + CSV)
│   ├── quarantine/            # Violations + validation summary
│   ├── remediation/           # Remediation log
│   ├── monitoring/            # Quality metrics time-series
│   └── profiles/              # Column statistics
├── tests/
│   ├── conftest.py            # Shared fixtures
│   ├── test_validation_rules.py   # 65 rule-level tests
│   └── test_validation_runner.py  # 13 orchestrator tests
└── pyproject.toml
```

## Configuration

All settings live in `src/config.py` and can be overridden via environment variables or a `.env` file.

| Setting | Default | Description |
|---------|---------|-------------|
| `GTFS_ALL_FEED_URL` | TFI combined zip | Live feed URL |
| `AUTO_REMEDIATE_ENABLED` | `False` | Enable auto-fix on pipeline run |
| `QUALITY_DRIFT_THRESHOLD` | `5.0` | % drop in quality score before alert |
| `RECORD_COUNT_DRIFT_THRESHOLD` | `10.0` | % change in record count before alert |
| `FEED_STALENESS_DAYS` | `7` | Days of no future service before staleness alert |
| `API_PORT` | `8000` | FastAPI port |
| `API_WORKERS` | `4` | Uvicorn worker processes |

### Enable Auto-Remediation

```bash
# .env
AUTO_REMEDIATE_ENABLED=True
```

Or pass directly to the pipeline:
```python
from src.ingestion.pipeline import run_full_pipeline
results = run_full_pipeline(auto_remediate=True)
```

## Validation Rules

39 rules across 3 severity levels. Rule failures are logged with the rule code; exceptions inside rules are caught and logged rather than silently discarded.

### CRITICAL (records quarantined)
- `STOP-001/002/003/004` — null stop_id, null coordinates, coordinates outside Ireland
- `ROUTE-001/002` — null route_id, agency_id not in agency.txt
- `TRIP-001/002/003` — null trip_id, orphaned route_id, orphaned service_id
- `ST-001/002/003/004` — orphaned trip_id/stop_id, null times, departure before arrival
- `CAL-001/002` — null service_id, start_date after end_date
- `REF-001/002` — agency/route cross-file mismatches

### WARNING (records flagged, not quarantined)
- Missing optional names, invalid enumerations, expired services, sequence issues

### INFO (informational)
- Encoding artifacts, single-stop trips, date ranges > 366 days

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
            required_files=[],          # list any cross-file deps here
        )

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        # return only the FAILING rows
        return df[df["some_col"].isna()]
```

Then add an instance to `ALL_RULES` at the bottom of `rules.py`. No changes to the runner are needed.

## Running Tests

```bash
pytest tests/ -v
```

78 tests covering all major validation rules and the runner orchestrator. Coverage report is written to `htmlcov/`.

## Power BI Integration

Gold tables are written as both Parquet (efficient) and CSV (Excel/Power BI compatible) to `outputs/gold/`.

1. Open Power BI Desktop
2. **Get Data → Folder** → point to `outputs/gold/`
3. Combine or connect files individually
4. Suggested visuals: route heatmaps, stop utilisation maps, quality score trends

## Troubleshooting

**Pipeline fails with network error**
The platform falls back to built-in sample data automatically. Check `logs/gtfs.log` for the exact URL that failed.

**API returns empty arrays**
Run the pipeline first (`python -m src.ingestion.pipeline`) to populate `outputs/gold/`.

**`keys must be str … not date` error in profiler**
Fixed — `top_10_values` keys are now always stringified before JSON serialisation.

**`WARNING: You must pass the application as an import string`**
Fixed — the uvicorn call uses `"src.api.main:app"` (string) not the `app` object directly.

**Dashboard shows stale data after pipeline re-run**
Cache TTL is 5 minutes. Use the browser refresh or wait for the next cache cycle.

**Memory errors with large feeds**
Reduce `BATCH_SIZE` in config or set `SAMPLE_SIZE` to a row limit for development.
