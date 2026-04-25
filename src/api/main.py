"""
FastAPI backend for the Irish GTFS Analytics Platform.

Exposes analytics and quality metrics via REST API endpoints.
"""
from fastapi import FastAPI, HTTPException, Query
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

def _agency_name_map() -> dict:
    """Build agency_id → agency_name lookup from the latest silver agency parquet."""
    try:
        files = sorted(settings.SILVER_OUTPUT.glob("agency_ingestion_date=*.parquet"))
        if not files:
            return {}
        import pandas as _pd
        df = _pd.read_parquet(files[-1], columns=["agency_id", "agency_name"])
        return dict(zip(df["agency_id"].astype(str), df["agency_name"].astype(str)))
    except Exception:
        return {}


@app.get("/routes")
async def get_routes(
    operator_id: Optional[str] = None,
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """Get routes with pagination and optional operator filter."""
    try:
        parquet_files = list(settings.GOLD_OUTPUT.glob("route_summary.parquet"))

        if not parquet_files:
            return ApiResponse(status="success", data=[], record_count=0)

        routes_df = read_parquet(parquet_files[0])

        # Resolve numeric agency_id → human-readable name at query time
        name_map = _agency_name_map()
        if name_map and "agency_name" in routes_df.columns:
            routes_df["agency_name"] = (
                routes_df["agency_name"].astype(str)
                .map(lambda v: name_map.get(v, v))   # replace if found, keep otherwise
            )

        # Ensure route_type is an integer so JS can look it up
        if "route_type" in routes_df.columns:
            routes_df["route_type"] = (
                routes_df["route_type"].fillna(-1).astype(int)
            )

        if operator_id:
            routes_df = routes_df[routes_df["agency_name"] == operator_id]

        routes = routes_df.iloc[offset:offset + limit].to_dict("records")
        return ApiResponse(status="success", data=routes, record_count=len(routes))

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


# ============= PIPELINE =============

@app.post("/pipeline/run")
async def run_pipeline():
    """Start the ingestion pipeline in the background."""
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
    import uvicorn

    # Pipeline state is in-process; multiple workers would each have an independent
    # copy of _pipeline_state. Force single worker unless explicitly set above 1 AND
    # the user understands the limitation.
    workers = settings.API_WORKERS if settings.API_WORKERS > 1 else 1
    uvicorn.run(
        "src.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=workers,
    )
