"""
FastAPI backend for the Irish GTFS Analytics Platform.

Exposes analytics and quality metrics via REST API endpoints.
"""
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
import pandas as pd
import json
import logging
import threading

from src.config import settings
from src.utils.logging import setup_logging
from src.utils.file_io import read_parquet, read_csv, list_parquet_files
from src.validation.runner import ValidationRunner
from src.ingestion.bronze import ingest_bronze_layer
from src.ingestion.silver import transform_to_silver_layer
from src.ingestion.gold import create_gold_layer
from src.profiling.profiler import profile_gtfs_files
from src.remediation.engine import apply_remediation
from src.monitoring.monitor import run_monitoring

logger = setup_logging(__name__)

# ── Pipeline state (shared across requests) ───────────────────
_pipeline_state: Dict[str, Any] = {
    "status": "idle",   # idle | running | completed | failed
    "messages": [],
    "started_at": None,
    "completed_at": None,
    "error": None,
    "lock": threading.Lock(),
}

_DISABLED_RULES_FILE = settings.OUTPUTS_ROOT / "disabled_rules.json"


def _load_disabled_rules() -> set:
    if _DISABLED_RULES_FILE.exists():
        return set(json.loads(_DISABLED_RULES_FILE.read_text()))
    return set()


def _save_disabled_rules(codes: set) -> None:
    _DISABLED_RULES_FILE.write_text(json.dumps(sorted(codes)))


class _UILogHandler(logging.Handler):
    """Captures log records and appends them to the shared pipeline state."""
    def emit(self, record: logging.LogRecord) -> None:
        with _pipeline_state["lock"]:
            _pipeline_state["messages"].append({
                "level": record.levelname,
                "text": record.getMessage(),
                "logger": record.name.split(".")[-1],
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            })


_ui_handler = _UILogHandler()
_ui_handler.setLevel(logging.INFO)


# ── Silver table cache (pre-loaded after pipeline, used by timetable endpoint) ──
_silver_cache: Dict[str, Any] = {"loaded": False, "lock": threading.Lock()}


def _load_silver_cache() -> None:
    """Load the four silver tables needed for timetable generation into memory."""
    try:
        silver = settings.SILVER_OUTPUT
        trips  = sorted(silver.glob("trips_ingestion_date=*.parquet"))
        st     = sorted(silver.glob("stop_times_ingestion_date=*.parquet"))
        stops  = sorted(silver.glob("stops_ingestion_date=*.parquet"))
        routes = sorted(silver.glob("routes_ingestion_date=*.parquet"))
        cal    = sorted(silver.glob("calendar_ingestion_date=*.parquet"))
        if not (trips and st and stops and routes):
            return
        with _silver_cache["lock"]:
            _silver_cache["trips"]  = pd.read_parquet(trips[-1])
            _silver_cache["stops"]  = pd.read_parquet(stops[-1])
            _silver_cache["routes"] = pd.read_parquet(routes[-1])
            _silver_cache["cal"]    = pd.read_parquet(cal[-1]) if cal else pd.DataFrame()
            # stop_times is large — load only needed columns
            _silver_cache["stop_times"] = pd.read_parquet(
                st[-1], columns=["trip_id", "stop_id", "stop_sequence", "departure_time"]
            )
            _silver_cache["loaded"] = True
        logger.info("Silver cache loaded for timetable serving")
        _build_routes_cache()
    except Exception as e:
        logger.warning("Failed to load silver cache: %s", e)


def _run_pipeline_background() -> None:
    root_logger = logging.getLogger("src")
    root_logger.addHandler(_ui_handler)
    try:
        from src.ingestion.pipeline import run_full_pipeline
        results = run_full_pipeline(auto_remediate=settings.AUTO_REMEDIATE_ENABLED)
        with _pipeline_state["lock"]:
            _pipeline_state["status"] = "completed" if results.get("success") else "failed"
            _pipeline_state["completed_at"] = datetime.now().isoformat()
            if not results.get("success"):
                _pipeline_state["error"] = results.get("error", "Unknown error")
        if results.get("success"):
            _load_silver_cache()   # pre-warm timetable cache after successful run
    except Exception as e:
        with _pipeline_state["lock"]:
            _pipeline_state["status"] = "failed"
            _pipeline_state["error"] = str(e)
            _pipeline_state["completed_at"] = datetime.now().isoformat()
    finally:
        root_logger.removeHandler(_ui_handler)


def _start_pipeline_if_idle(reason: str = "") -> bool:
    """Start pipeline in background if not already running. Returns True if started."""
    with _pipeline_state["lock"]:
        if _pipeline_state["status"] == "running":
            return False
        _pipeline_state["status"] = "running"
        _pipeline_state["messages"] = []
        _pipeline_state["started_at"] = datetime.now().isoformat()
        _pipeline_state["completed_at"] = None
        _pipeline_state["error"] = None
    if reason:
        logger.info(reason)
    threading.Thread(target=_run_pipeline_background, daemon=True).start()
    return True


def _scheduler_loop() -> None:
    """Background thread: run pipeline daily at ~03:00 local time."""
    import time
    while True:
        now = datetime.now()
        # Sleep until next 03:00
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(day=now.day + 1)
        sleep_secs = (next_run - now).total_seconds()
        time.sleep(sleep_secs)
        _start_pipeline_if_idle("Scheduled daily pipeline refresh")

# Pre-warm silver cache on startup (non-blocking)
threading.Thread(target=_load_silver_cache, daemon=True).start()

# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="Irish GTFS Analytics and Quality Platform API",
)


@app.on_event("startup")
async def _on_startup():
    # Auto-run pipeline on first boot if no gold data exists yet
    gold_exists = any(settings.GOLD_OUTPUT.glob("route_summary.parquet"))
    if not gold_exists:
        logger.info("No gold data found — starting initial pipeline run automatically")
        _start_pipeline_if_idle("Auto-running pipeline (first boot — no data found)")
    else:
        logger.info("Gold data found — skipping auto-run on startup")

    # Start daily refresh scheduler in background
    threading.Thread(target=_scheduler_loop, daemon=True).start()

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Response models
class ApiResponse(BaseModel):
    status: str
    data: Any
    record_count: int = 0
    timestamp: str = datetime.now().isoformat()


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
    timestamp: str = datetime.now().isoformat()


# ============= ROOT =============

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api-docs", include_in_schema=False)
async def api_docs():
    return RedirectResponse(url="/docs")


# ============= HEALTH CHECK =============

@app.get("/health")
async def health_check() -> ApiResponse:
    """Health check endpoint."""
    return ApiResponse(
        status="healthy",
        data={"message": "Irish GTFS Analytics Platform is running"},
        record_count=0,
    )


# ============= OPERATORS =============

@app.get("/operators")
async def get_operators() -> ApiResponse:
    """Get list of all operators."""
    try:
        # Try to read from Silver layer
        operators_file = settings.SILVER_OUTPUT / "agency_ingestion_date=*.parquet"
        parquet_files = list(settings.SILVER_OUTPUT.glob("agency_ingestion_date=*.parquet"))
        
        if parquet_files:
            agency_df = read_parquet(parquet_files[-1])
            operators = agency_df[["agency_id", "agency_name", "agency_url"]].to_dict("records")
            
            return ApiResponse(
                status="success",
                data=operators,
                record_count=len(operators),
            )
        else:
            return ApiResponse(
                status="success",
                data=[],
                record_count=0,
            )
    except Exception as e:
        logger.error(f"Error fetching operators: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============= ROUTES =============

_DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Module-level route cache — built once from silver, reused on every request
_routes_cache: Dict[str, Any] = {"df": None, "lock": threading.Lock()}


def _build_routes_cache() -> None:
    """
    Build the fully-enriched routes DataFrame once and hold it in memory.
    Called at startup and after every successful pipeline run.
    """
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("route_summary.parquet"))
        if not parquet_files:
            return

        routes_df = pd.read_parquet(parquet_files[0])

        # Agency names from silver cache (already in memory)
        with _silver_cache["lock"]:
            agency_loaded = _silver_cache.get("loaded", False)
            if agency_loaded and "stops" in _silver_cache:
                # Rebuild agency map from in-memory silver
                try:
                    silver_files = sorted(settings.SILVER_OUTPUT.glob("agency_ingestion_date=*.parquet"))
                    if silver_files:
                        ag = pd.read_parquet(silver_files[-1], columns=["agency_id", "agency_name"])
                        name_map = dict(zip(ag["agency_id"].astype(str), ag["agency_name"].astype(str)))
                    else:
                        name_map = {}
                except Exception:
                    name_map = {}
            else:
                name_map = {}

        if name_map and "agency_name" in routes_df.columns:
            routes_df["agency_name"] = routes_df["agency_name"].astype(str).map(
                lambda v: name_map.get(v, v)
            )
        if "route_type" in routes_df.columns:
            routes_df["route_type"] = routes_df["route_type"].fillna(-1).astype(int)

        # Schedule enrichment using in-memory silver cache
        with _silver_cache["lock"]:
            if _silver_cache.get("loaded"):
                trips = _silver_cache["trips"][["trip_id", "route_id", "service_id"]]
                cal   = _silver_cache["cal"][["service_id"] + [d for d in _DOW if d in _silver_cache["cal"].columns]]
                st    = _silver_cache["stop_times"][["trip_id", "departure_time"]]
            else:
                trips = cal = st = None

        if trips is not None:
            # Days of week
            rc = trips[["route_id", "service_id"]].drop_duplicates().merge(cal, on="service_id", how="left")
            dow_cols = [d for d in _DOW if d in rc.columns]
            days_df = rc.groupby("route_id")[dow_cols].max().reset_index()
            for d in dow_cols:
                days_df[d] = days_df[d].fillna(0).astype(int).astype(bool)

            # First / last departure
            tt = trips[["trip_id", "route_id"]].merge(st, on="trip_id", how="left").dropna(subset=["departure_time"])
            parts = tt["departure_time"].astype(str).str.split(":", expand=True)
            tt["_s"] = pd.to_numeric(parts[0], errors="coerce") * 3600 + pd.to_numeric(parts[1], errors="coerce") * 60
            tt = tt.dropna(subset=["_s"])
            idx_min = tt.groupby("route_id")["_s"].idxmin()
            idx_max = tt.groupby("route_id")["_s"].idxmax()
            times_df = pd.DataFrame({
                "route_id":       tt.loc[idx_min, "route_id"].values,
                "first_departure": tt.loc[idx_min, "departure_time"].values,
                "last_departure":  tt.loc[idx_max, "departure_time"].values,
            })

            sched = days_df.merge(times_df, on="route_id", how="left").set_index("route_id")
            routes_df = routes_df.join(sched, on="route_id", how="left")

        with _routes_cache["lock"]:
            _routes_cache["df"] = routes_df

        logger.info("Routes cache built: %d routes", len(routes_df))
    except Exception as e:
        logger.warning("Failed to build routes cache: %s", e)


def _agency_name_map() -> dict:
    """Agency id→name map — reads from silver parquet (used by timetable endpoint)."""
    try:
        files = sorted(settings.SILVER_OUTPUT.glob("agency_ingestion_date=*.parquet"))
        if not files:
            return {}
        df = pd.read_parquet(files[-1], columns=["agency_id", "agency_name"])
        return dict(zip(df["agency_id"].astype(str), df["agency_name"].astype(str)))
    except Exception:
        return {}


_ROUTES_SORTABLE = {
    "route_short_name", "route_long_name", "agency_name",
    "route_type", "total_trips", "first_departure",
}


@app.get("/routes")
async def get_routes(
    operator_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
) -> ApiResponse:
    """Get routes from the in-memory cache with optional search, sort, and pagination."""
    try:
        with _routes_cache["lock"]:
            routes_df = _routes_cache.get("df")

        if routes_df is None:
            pf = list(settings.GOLD_OUTPUT.glob("route_summary.parquet"))
            if not pf:
                return ApiResponse(status="success", data=[], record_count=0)
            routes_df = pd.read_parquet(pf[0])

        if operator_id:
            routes_df = routes_df[routes_df["agency_name"] == operator_id]

        if search:
            q = search.lower()
            mask = (
                routes_df["route_short_name"].astype(str).str.lower().str.contains(q, na=False)
                | routes_df["route_long_name"].astype(str).str.lower().str.contains(q, na=False)
                | routes_df["agency_name"].astype(str).str.lower().str.contains(q, na=False)
            )
            routes_df = routes_df[mask]

        # Sorting
        if sort_by and sort_by in _ROUTES_SORTABLE and sort_by in routes_df.columns:
            asc = sort_dir.lower() != "desc"
            try:
                if sort_by == "route_short_name":
                    # Natural numeric sort: "1","2","10" before "X1","N22"
                    routes_df = routes_df.copy()
                    routes_df["_sk"] = pd.to_numeric(routes_df["route_short_name"], errors="coerce")
                    routes_df = routes_df.sort_values(
                        ["_sk", "route_short_name"], ascending=[asc, asc], na_position="last"
                    ).drop(columns=["_sk"])
                elif sort_by == "first_departure":
                    # Sort by time-of-day (HH:MM:SS string → seconds)
                    routes_df = routes_df.copy()
                    parts = routes_df["first_departure"].fillna("").astype(str).str.split(":", expand=True)
                    secs = (
                        pd.to_numeric(parts.get(0, pd.Series(0, index=routes_df.index)), errors="coerce") * 3600
                        + pd.to_numeric(parts.get(1, pd.Series(0, index=routes_df.index)), errors="coerce") * 60
                    )
                    routes_df["_sk"] = secs.values
                    routes_df = routes_df.sort_values("_sk", ascending=asc, na_position="last").drop(columns=["_sk"])
                else:
                    routes_df = routes_df.sort_values(sort_by, ascending=asc, na_position="last")
            except Exception as sort_err:
                logger.debug("Sort failed for %s: %s", sort_by, sort_err)

        total = len(routes_df)
        page  = routes_df.iloc[offset:offset + limit]

        bool_cols = [c for c in page.columns if page[c].dtype == bool]
        for c in bool_cols:
            page = page.copy()
            page[c] = page[c].astype(int)

        return ApiResponse(
            status="success",
            data=page.to_dict("records"),
            record_count=total,
        )

    except Exception as e:
        logger.error(f"Error fetching routes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============= STOPS =============

@app.get("/stops")
async def get_stops(
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    limit: int = Query(100, ge=1, le=10000),
) -> ApiResponse:
    """Get stops with optional bounding box filter."""
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("stop_activity.parquet"))
        
        if parquet_files:
            stops_df = read_parquet(parquet_files[0])
            
            # Apply bounding box filter
            if lat_min is not None:
                stops_df = stops_df[stops_df["latitude"] >= lat_min]
            if lat_max is not None:
                stops_df = stops_df[stops_df["latitude"] <= lat_max]
            if lon_min is not None:
                stops_df = stops_df[stops_df["longitude"] >= lon_min]
            if lon_max is not None:
                stops_df = stops_df[stops_df["longitude"] <= lon_max]
            
            stops_limited = stops_df.head(limit)
            stops = stops_limited.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=stops,
                record_count=len(stops),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        logger.error(f"Error fetching stops: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============= STATISTICS =============

@app.get("/stats/operator-summary")
async def get_operator_summary() -> ApiResponse:
    """Get operator summary statistics."""
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("operator_summary.parquet"))
        
        if parquet_files:
            summary_df = read_parquet(parquet_files[0])
            summary = summary_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=summary,
                record_count=len(summary),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/route-summary")
async def get_route_summary() -> ApiResponse:
    """Get route summary statistics."""
    try:
        with _routes_cache["lock"]:
            cached_df = _routes_cache.get("df")
        if cached_df is not None:
            return ApiResponse(status="success", data=cached_df.to_dict("records"), record_count=len(cached_df))

        parquet_files = list(settings.GOLD_OUTPUT.glob("route_summary.parquet"))
        if not parquet_files:
            return ApiResponse(status="success", data=[], record_count=0)

        summary_df = read_parquet(parquet_files[0])
        name_map = _agency_name_map()
        if name_map and "agency_name" in summary_df.columns:
            summary_df["agency_name"] = summary_df["agency_name"].astype(str).map(lambda v: name_map.get(v, v))
        if "route_type" in summary_df.columns:
            summary_df["route_type"] = summary_df["route_type"].fillna(-1).astype(int)

        return ApiResponse(status="success", data=summary_df.to_dict("records"), record_count=len(summary_df))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/stop-activity")
async def get_stop_activity() -> ApiResponse:
    """Get stop activity statistics."""
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("stop_activity.parquet"))
        
        if parquet_files:
            activity_df = read_parquet(parquet_files[0])
            activity = activity_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=activity,
                record_count=len(activity),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/headway")
async def get_headway_analysis() -> ApiResponse:
    """Get headway analysis."""
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("headway_analysis.parquet"))
        
        if parquet_files:
            headway_df = read_parquet(parquet_files[0])
            headway = headway_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=headway,
                record_count=len(headway),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= VALIDATION =============

@app.get("/validation/summary")
async def get_validation_summary() -> ApiResponse:
    """Get validation summary report."""
    try:
        csv_path = settings.GOLD_OUTPUT / "validation_summary.csv"
        
        if csv_path.exists():
            summary_df = read_csv(csv_path)
            summary = summary_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=summary,
                record_count=len(summary),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/validation/issues")
async def get_validation_issues(
    rule_code: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(100, ge=1, le=10000),
) -> ApiResponse:
    """Get validation issues with optional filters."""
    try:
        parquet_files = list(settings.QUARANTINE_OUTPUT.glob("quarantine_date=*.parquet"))
        
        if parquet_files:
            # Read the latest quarantine file
            quarantine_df = read_parquet(parquet_files[-1])
            
            # Apply filters
            if rule_code:
                quarantine_df = quarantine_df[quarantine_df["rule_code"] == rule_code]
            
            if severity:
                quarantine_df = quarantine_df[quarantine_df["severity"] == severity]
            
            issues = quarantine_df.head(limit).to_dict("records")
            
            return ApiResponse(
                status="success",
                data=issues,
                record_count=len(issues),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/validation/rule/{rule_code}")
async def get_rule_details(rule_code: str) -> ApiResponse:
    """Get details for a specific validation rule."""
    try:
        csv_path = settings.GOLD_OUTPUT / "validation_summary.csv"
        
        if csv_path.exists():
            summary_df = read_csv(csv_path)
            rule_summary = summary_df[summary_df["rule_code"] == rule_code]
            
            if len(rule_summary) > 0:
                return ApiResponse(
                    status="success",
                    data=rule_summary.to_dict("records")[0],
                    record_count=1,
                )
            else:
                return ApiResponse(status="success", data={}, record_count=0)
        else:
            return ApiResponse(status="success", data={}, record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/validation/export")
async def export_validation_data() -> FileResponse:
    """Export all validation data as CSV."""
    csv_path = settings.GOLD_OUTPUT / "validation_summary.csv"
    
    if csv_path.exists():
        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename="validation_summary.csv",
        )
    else:
        raise HTTPException(status_code=404, detail="Validation data not found")


# ============= REMEDIATION =============

@app.get("/remediation/summary")
async def get_remediation_summary() -> ApiResponse:
    """Get remediation summary."""
    try:
        csv_path = settings.GOLD_OUTPUT / "remediation_log.csv"
        
        if csv_path.exists():
            remediation_df = read_csv(csv_path)
            summary = remediation_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=summary,
                record_count=len(summary),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= MONITORING =============

@app.get("/monitoring/latest")
async def get_latest_monitoring() -> ApiResponse:
    """Get latest monitoring report."""
    try:
        parquet_files = sorted(list(settings.MONITORING_OUTPUT.glob("monitoring_log_date=*.parquet")))
        
        if parquet_files:
            monitoring_df = read_parquet(parquet_files[-1])
            latest = monitoring_df.tail(1).to_dict("records")[0] if len(monitoring_df) > 0 else {}
            
            return ApiResponse(
                status="success",
                data=latest,
                record_count=1,
            )
        else:
            return ApiResponse(status="success", data={}, record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/monitoring/history")
async def get_monitoring_history(
    limit: int = Query(100, ge=1, le=10000),
) -> ApiResponse:
    """Get monitoring history."""
    try:
        parquet_files = list(settings.MONITORING_OUTPUT.glob("monitoring_log_date=*.parquet"))
        
        if parquet_files:
            all_records = []
            for pf in sorted(parquet_files):
                df = read_parquet(pf)
                all_records.extend(df.to_dict("records"))
            
            records_limited = all_records[-limit:]
            
            return ApiResponse(
                status="success",
                data=records_limited,
                record_count=len(records_limited),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/monitoring/alerts")
async def get_monitoring_alerts() -> ApiResponse:
    """Get monitoring alerts."""
    try:
        csv_path = settings.GOLD_OUTPUT / "monitoring_alerts.csv"
        
        if csv_path.exists():
            alerts_df = read_csv(csv_path)
            alerts = alerts_df.to_dict("records")
            
            return ApiResponse(
                status="success",
                data=alerts,
                record_count=len(alerts),
            )
        else:
            return ApiResponse(status="success", data=[], record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= EXPORT =============

@app.get("/export/{table_name}")
async def export_table(table_name: str) -> FileResponse:
    """Export a Gold layer table as CSV."""
    csv_path = settings.GOLD_OUTPUT / f"{table_name}.csv"
    
    if csv_path.exists():
        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename=f"{table_name}.csv",
        )
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Table {table_name} not found"
        )


# ============= PROFILES =============

@app.get("/profile/{file_name}")
async def get_profile(file_name: str) -> ApiResponse:
    """Get data profile for a GTFS file."""
    try:
        json_files = list(settings.PROFILES_OUTPUT.glob(f"{file_name}_profile_*.json"))
        
        if json_files:
            with open(json_files[-1], "r") as f:
                profile = json.load(f)
            
            return ApiResponse(
                status="success",
                data=profile,
                record_count=1,
            )
        else:
            return ApiResponse(status="success", data={}, record_count=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= TIMETABLE =============

@app.get("/routes/{route_id}/timetable")
async def get_route_timetable(
    route_id: str,
    direction_id: int = Query(0, ge=0, le=1),
) -> ApiResponse:
    """
    Return a timetable grid for one route: stops as rows, trips as columns.
    Uses the in-memory silver cache pre-loaded at startup / after pipeline run.
    """
    try:
        with _silver_cache["lock"]:
            if not _silver_cache.get("loaded"):
                return ApiResponse(status="success", data={"error": "cache_not_ready"}, record_count=0)
            trips_df  = _silver_cache["trips"]
            st_df_all = _silver_cache["stop_times"]
            stops_df  = _silver_cache["stops"]
            routes_df = _silver_cache["routes"]
            cal_df    = _silver_cache["cal"]

        # ── Filter trips ──────────────────────────────────────────
        route_trips = trips_df[trips_df["route_id"] == route_id].copy()
        route_trips["direction_id"] = route_trips["direction_id"].fillna(0).astype(int)
        dir_trips = route_trips[route_trips["direction_id"] == direction_id]
        if dir_trips.empty:
            dir_trips = route_trips          # fall back if direction_id not in feed

        trip_ids = dir_trips["trip_id"].tolist()
        if not trip_ids:
            return ApiResponse(status="success", data={}, record_count=0)

        # ── Stop times for this set of trips ─────────────────────
        st = st_df_all[st_df_all["trip_id"].isin(trip_ids)].copy()
        st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce").fillna(0).astype(int)

        # Reference trip = the one covering the most stops
        ref_trip = st.groupby("trip_id")["stop_id"].count().idxmax()
        ref_stops = (
            st[st["trip_id"] == ref_trip]
            .sort_values("stop_sequence")[["stop_sequence", "stop_id"]]
            .drop_duplicates("stop_id")
        )

        # ── Stop metadata ─────────────────────────────────────────
        stops_idx = stops_df.set_index("stop_id")
        stop_rows = []
        for _, row in ref_stops.iterrows():
            sid = row["stop_id"]
            meta = stops_idx.loc[sid] if sid in stops_idx.index else {}
            def _get(col):
                return str(meta[col]) if hasattr(meta, "__getitem__") and col in meta.index else str(getattr(meta, col, ""))
            raw = _get("stop_name") or sid
            parts = raw.split(",", 1)
            stop_rows.append({
                "stop_sequence": int(row["stop_sequence"]),
                "stop_id":       sid,
                "stop_code":     _get("stop_code"),
                "stop_name":     parts[0].strip(),
                "stop_location": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
            })

        # ── Trip columns sorted by first-stop departure ───────────
        def _secs(t):
            try:
                p = str(t).split(":")
                return int(p[0]) * 3600 + int(p[1]) * 60
            except Exception:
                return 999999

        first_seq = ref_stops.iloc[0]["stop_sequence"]
        first_times = st[st["stop_sequence"] == first_seq].set_index("trip_id")["departure_time"].to_dict()
        headsign_map = dir_trips.set_index("trip_id")["trip_headsign"].to_dict()

        # Per-trip service-day indicators using calendar
        _DOW_SHORT = ["Mo","Tu","We","Th","Fr","Sa","Su"]
        _DOW_FULL  = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        svc_days_map: dict = {}
        if not cal_df.empty:
            for _, cr in cal_df.iterrows():
                svc_days_map[cr["service_id"]] = [
                    _DOW_SHORT[i] for i, d in enumerate(_DOW_FULL) if cr.get(d, 0)
                ]
        svc_by_trip = dir_trips.set_index("trip_id")["service_id"].to_dict() if "service_id" in dir_trips.columns else {}

        trip_cols = []
        for idx, tid in enumerate(sorted(trip_ids, key=lambda t: _secs(first_times.get(t, "99:99"))), start=1):
            trip_st = st[st["trip_id"] == tid].set_index("stop_sequence")["departure_time"].to_dict()
            times_by_seq = {}
            for seq in ref_stops["stop_sequence"]:
                raw_t = trip_st.get(seq)
                if raw_t and str(raw_t) not in ("nan", "None", ""):
                    p = str(raw_t).split(":")
                    h = int(p[0]) % 24    # normalise >24h GTFS times
                    times_by_seq[str(seq)] = f"{h:02d}:{p[1]}"
                else:
                    times_by_seq[str(seq)] = None
            svc_id = svc_by_trip.get(tid, "")
            trip_cols.append({
                "trip_id":      tid,
                "trip_num":     idx,
                "headsign":     headsign_map.get(tid, ""),
                "times":        times_by_seq,
                "service_days": svc_days_map.get(svc_id, []),
            })

        # ── Days label ────────────────────────────────────────────
        days_label = "—"
        if not cal_df.empty and "service_id" in dir_trips.columns:
            _DOW = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
            svc_cal = cal_df[cal_df["service_id"].isin(dir_trips["service_id"].unique())]
            if not svc_cal.empty:
                active = [d for d in _DOW if d in svc_cal.columns and svc_cal[d].max()]
                mapping = {
                    tuple("monday tuesday wednesday thursday friday saturday sunday".split()): "Monday – Sunday",
                    tuple("monday tuesday wednesday thursday friday".split()):                "Monday – Friday",
                    tuple("saturday sunday".split()):                                        "Saturday – Sunday",
                    ("saturday",):                                                            "Saturday only",
                    ("sunday",):                                                              "Sunday only",
                }
                days_label = mapping.get(tuple(active), ", ".join(d.capitalize() for d in active)) or "—"

        # ── Route display names ───────────────────────────────────
        r_row = routes_df[routes_df["route_id"] == route_id]
        name_map = _agency_name_map()

        def _val(col):
            return str(r_row[col].iloc[0]) if not r_row.empty and col in r_row.columns else ""

        agency_raw  = _val("agency_id") or _val("agency_name")
        agency_name = name_map.get(agency_raw, agency_raw)

        return ApiResponse(
            status="success",
            data={
                "route_short_name": _val("route_short_name") or route_id,
                "route_long_name":  _val("route_long_name"),
                "agency_name":      agency_name,
                "direction_id":     direction_id,
                "days":             days_label,
                "stops":            stop_rows,
                "trips":            trip_cols,
            },
            record_count=len(trip_cols),
        )

    except Exception as e:
        logger.error("Timetable error for route %s: %s", route_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============= PIPELINE =============

@app.post("/pipeline/run")
async def run_pipeline(x_admin_token: Optional[str] = Header(default=None)):
    """Start the ingestion pipeline. Requires admin token when PIPELINE_ADMIN_TOKEN is configured."""
    required = settings.PIPELINE_ADMIN_TOKEN
    if required and x_admin_token != required:
        raise HTTPException(status_code=401, detail="Admin token required to run the pipeline")
    started = _start_pipeline_if_idle()
    if not started:
        raise HTTPException(status_code=409, detail="Pipeline is already running")
    return {"status": "started", "started_at": _pipeline_state["started_at"]}


@app.get("/pipeline/status")
async def get_pipeline_status():
    """Get current pipeline status."""
    with _pipeline_state["lock"]:
        return {
            "status": _pipeline_state["status"],
            "started_at": _pipeline_state["started_at"],
            "completed_at": _pipeline_state["completed_at"],
            "error": _pipeline_state["error"],
            "message_count": len(_pipeline_state["messages"]),
        }


@app.get("/pipeline/schedule")
async def get_pipeline_schedule():
    """Return next scheduled daily run time."""
    now = datetime.now()
    next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if next_run <= now:
        from datetime import timedelta
        next_run = next_run + timedelta(days=1)
    return {"next_scheduled_run": next_run.isoformat(), "schedule": "Daily at 03:00 local time"}


@app.get("/pipeline/messages")
async def get_pipeline_messages(since: int = Query(0, ge=0)):
    """Poll for new log messages since a given index."""
    with _pipeline_state["lock"]:
        msgs = _pipeline_state["messages"][since:]
        total = len(_pipeline_state["messages"])
    return {"messages": msgs, "next_index": total}


# ============= RULES =============

@app.get("/rules")
async def get_rules():
    """Return all validation rules with their metadata and enabled/disabled state."""
    from src.validation.rules import ALL_RULES
    disabled = _load_disabled_rules()
    rules = [
        {
            "rule_code": r.rule_code,
            "description": r.description,
            "severity": r.severity,
            "source_file": r.source_file,
            "required_files": r.required_files,
            "enabled": r.rule_code not in disabled,
        }
        for r in ALL_RULES
    ]
    return ApiResponse(status="success", data=rules, record_count=len(rules))


@app.post("/rules/{rule_code}/enable")
async def enable_rule(rule_code: str):
    """Enable a previously disabled rule."""
    disabled = _load_disabled_rules()
    disabled.discard(rule_code)
    _save_disabled_rules(disabled)
    return {"rule_code": rule_code, "enabled": True}


@app.post("/rules/{rule_code}/disable")
async def disable_rule(rule_code: str):
    """Disable a rule so it is skipped during validation."""
    disabled = _load_disabled_rules()
    disabled.add(rule_code)
    _save_disabled_rules(disabled)
    return {"rule_code": rule_code, "enabled": False}


if __name__ == "__main__":
    # Prefer: make dev   (uvicorn --reload, for development)
    #         make serve (uvicorn, for production)
    # This block is a convenience fallback only.
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
    )
