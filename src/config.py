"""
Global configuration for the Irish GTFS Analytics Platform.
"""
import os
from typing import Dict, Optional
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    # Project paths
    PROJECT_ROOT: Path = Field(default=_PROJECT_ROOT)
    DATA_ROOT: Path = Field(default=_PROJECT_ROOT / "data")
    OUTPUTS_ROOT: Path = Field(default=_PROJECT_ROOT / "outputs")
    BRONZE_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "bronze")
    SILVER_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "silver")
    GOLD_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "gold")
    QUARANTINE_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "quarantine")
    REMEDIATION_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "remediation")
    MONITORING_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "monitoring")
    PROFILES_OUTPUT: Path = Field(default=_PROJECT_ROOT / "outputs" / "profiles")

    # GTFS Data Source
    GTFS_ALL_FEED_URL: str = "https://www.transportforireland.ie/transitData/Data/GTFS_All.zip"

    # Ireland bounding box for geospatial validation
    IRELAND_LAT_MIN: float = 51.2
    IRELAND_LAT_MAX: float = 55.5
    IRELAND_LON_MIN: float = -10.7
    IRELAND_LON_MAX: float = -5.9

    # Database configuration
    DATABASE_TYPE: str = Field(default="sqlite")  # sqlite or postgresql
    SQLITE_DB_PATH: Path = Field(default=_PROJECT_ROOT / "gtfs.db")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="gtfs_analytics")
    POSTGRES_USER: str = Field(default="gtfs_user")
    POSTGRES_PASSWORD: str = Field(default="")

    # Validation configuration
    AUTO_REMEDIATE_ENABLED: bool = Field(default=False)
    AUTO_REMEDIATE_RULES: Dict[str, bool] = Field(
        default={
            "STOP-005": True,  # Populate unknown stop names
            "STOP-007": True,  # Attempt re-encoding
            "ROUTE-003": True,  # Use route_id as short name
            "TRIP-004": True,  # Set shape_id to null
            "ST-005": True,  # Convert times exceeding 29:59:59
            "ST-007": True,  # Flag zero dwell as interpolated
            "CAL-003": True,  # Flag inactive services
            "CAL-004": True,  # Flag expired services
            "SHP-001": True,  # Move orphaned shapes
            "SHP-003": True,  # Deduplicate shape points
        }
    )

    # Monitoring thresholds
    QUALITY_DRIFT_THRESHOLD: float = Field(default=5.0)  # percentage points
    RECORD_COUNT_DRIFT_THRESHOLD: float = Field(default=10.0)  # percentage
    FEED_STALENESS_DAYS: int = Field(default=7)  # days until next active service

    # API configuration
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
    API_TITLE: str = Field(default="Irish GTFS Analytics API")
    API_VERSION: str = Field(default="0.1.0")
    API_WORKERS: int = Field(default=1)  # >1 workers splits in-process pipeline state
    PIPELINE_ADMIN_TOKEN: str = Field(default="")  # empty = no auth; set a secret to protect /pipeline/run

    # Dashboard configuration
    DASHBOARD_THEME: str = Field(default="light")
    DASHBOARD_PASTEL_COLORS: Dict[str, str] = Field(
        default={
            "mint": "#C6E0B4",
            "lavender": "#D9D2E9",
            "peach": "#F8CBAD",
            "sky_blue": "#B4C7E7",
            "white": "#FEFDFB",
            "critical": "#F4CCCC",
            "warning": "#FCE5CD",
            "info": "#CFE2F3",
            "passing": "#D9EAD3",
        }
    )

    # Logging configuration
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    LOG_FILE: Path = Field(default=_PROJECT_ROOT / "logs" / "gtfs.log")

    # Processing
    BATCH_SIZE: int = Field(default=10000)
    SAMPLE_SIZE: Optional[int] = Field(default=None)  # None means process all records
    MAX_WORKERS: int = Field(default=4)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    def __init__(self, **data):
        super().__init__(**data)
        # Ensure all output directories exist
        self.BRONZE_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.SILVER_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.GOLD_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.QUARANTINE_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.REMEDIATION_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.MONITORING_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.PROFILES_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.DATA_ROOT.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
