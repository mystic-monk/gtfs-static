"""
Monitoring and alerting layer for the Irish GTFS Analytics Platform.

Runs after each ingestion and computes time-series quality metrics.
"""
import pandas as pd
import logging
from typing import Dict, Optional
from datetime import datetime, date, timedelta
from pathlib import Path

from src.config import settings
from src.utils.logging import setup_logging
from src.utils.file_io import write_parquet, write_csv, read_parquet, list_parquet_files

logger = setup_logging(__name__)


class MonitoringLayer:
    """
    Monitor data quality and detect issues.
    """
    
    def __init__(self):
        self.ingestion_timestamp = datetime.now()
        self.monitoring_records = []
        self.alerts = []
    
    def compute_quality_metrics(
        self,
        validation_summary_df: pd.DataFrame,
        quarantine_df: pd.DataFrame,
        gtfs_dfs: Dict[str, pd.DataFrame],
    ) -> Dict:
        """
        Compute quality metrics for current ingestion.
        
        Args:
            validation_summary_df: Validation summary from rules engine
            quarantine_df: Quarantined records
            gtfs_dfs: Dictionary of GTFS DataFrames
            
        Returns:
            Metrics dictionary
        """
        metrics = {
            "ingestion_timestamp": self.ingestion_timestamp,
            "ingestion_date": self.ingestion_timestamp.strftime("%Y-%m-%d"),
        }
        
        # Overall quality score
        total_records = sum(len(df) for df in gtfs_dfs.values())
        critical_violations = len(quarantine_df) if len(quarantine_df) > 0 else 0
        
        if total_records > 0:
            quality_score = ((total_records - critical_violations) / total_records) * 100
        else:
            quality_score = 100.0
        
        metrics["quality_score"] = quality_score
        metrics["total_records_ingested"] = total_records
        metrics["total_critical_violations"] = critical_violations
        
        # Violations by severity
        if len(validation_summary_df) > 0:
            critical = validation_summary_df[validation_summary_df["severity"] == "CRITICAL"]
            warning = validation_summary_df[validation_summary_df["severity"] == "WARNING"]
            info = validation_summary_df[validation_summary_df["severity"] == "INFO"]
            
            metrics["critical_violations"] = int(critical["violation_count"].sum())
            metrics["warning_violations"] = int(warning["violation_count"].sum())
            metrics["info_violations"] = int(info["violation_count"].sum())
        
        return metrics
    
    def detect_quality_drift(
        self,
        current_metrics: Dict,
        previous_metrics: Optional[Dict] = None,
    ) -> list:
        """
        Detect quality degradation compared to previous ingestion.
        
        Args:
            current_metrics: Current ingestion metrics
            previous_metrics: Previous ingestion metrics (if available)
            
        Returns:
            List of alerts if drift detected
        """
        alerts = []
        
        if previous_metrics is None:
            return alerts
        
        # Check quality score drift
        current_score = current_metrics.get("quality_score", 100)
        previous_score = previous_metrics.get("quality_score", 100)
        
        drift = previous_score - current_score
        if drift > settings.QUALITY_DRIFT_THRESHOLD:
            alerts.append({
                "alert_type": "QUALITY_DRIFT",
                "severity": "WARNING",
                "message": f"Quality score dropped by {drift:.1f} percentage points",
                "previous_value": previous_score,
                "current_value": current_score,
                "threshold": settings.QUALITY_DRIFT_THRESHOLD,
                "ingestion_date": current_metrics["ingestion_date"],
            })
        
        return alerts
    
    def detect_record_count_drift(
        self,
        current_records: Dict[str, int],
        previous_records: Optional[Dict[str, int]] = None,
    ) -> list:
        """
        Detect significant record count changes.
        
        Args:
            current_records: Current record counts by file
            previous_records: Previous record counts (if available)
            
        Returns:
            List of alerts if drift detected
        """
        alerts = []
        
        if previous_records is None:
            return alerts
        
        for file_name, current_count in current_records.items():
            if file_name in previous_records:
                previous_count = previous_records[file_name]
                
                if previous_count > 0:
                    pct_change = abs(current_count - previous_count) / previous_count * 100
                    
                    if pct_change > settings.RECORD_COUNT_DRIFT_THRESHOLD:
                        alerts.append({
                            "alert_type": "RECORD_COUNT_DRIFT",
                            "severity": "WARNING",
                            "file_name": file_name,
                            "message": f"{file_name} record count changed by {pct_change:.1f}%",
                            "previous_count": previous_count,
                            "current_count": current_count,
                            "threshold_pct": settings.RECORD_COUNT_DRIFT_THRESHOLD,
                        })
        
        return alerts
    
    def detect_feed_staleness(
        self,
        calendar_df: pd.DataFrame,
    ) -> list:
        """
        Detect if feed has no active services in near future.
        
        Args:
            calendar_df: Calendar data
            
        Returns:
            List of alerts if feed is stale
        """
        alerts = []
        
        if len(calendar_df) == 0:
            return alerts
        
        today = date.today()
        future_date = today + timedelta(days=settings.FEED_STALENESS_DAYS)
        
        # Check if any service is active in the next N days
        has_future_service = False
        max_end_date = None
        
        for _, row in calendar_df.iterrows():
            try:
                end_date = row["end_date"]
                if pd.notna(end_date) and isinstance(end_date, date):
                    if end_date >= future_date:
                        has_future_service = True
                    if max_end_date is None or end_date > max_end_date:
                        max_end_date = end_date
            except:
                pass
        
        if not has_future_service:
            alerts.append({
                "alert_type": "FEED_STALENESS",
                "severity": "CRITICAL",
                "message": f"No active services within next {settings.FEED_STALENESS_DAYS} days",
                "max_service_date": max_end_date,
                "today": today,
                "threshold_days": settings.FEED_STALENESS_DAYS,
            })
        
        return alerts
    
    def detect_schema_drift(
        self,
        current_columns: Dict[str, list],
        previous_columns: Optional[Dict[str, list]] = None,
    ) -> list:
        """
        Detect schema changes between ingestions.
        
        Args:
            current_columns: Current schema (file -> [columns])
            previous_columns: Previous schema (if available)
            
        Returns:
            List of alerts if schema changed
        """
        alerts = []
        
        if previous_columns is None:
            return alerts
        
        for file_name, current_cols in current_columns.items():
            if file_name in previous_columns:
                previous_cols = set(previous_columns[file_name])
                current_cols_set = set(current_cols)
                
                new_cols = current_cols_set - previous_cols
                missing_cols = previous_cols - current_cols_set
                
                if new_cols or missing_cols:
                    alerts.append({
                        "alert_type": "SCHEMA_DRIFT",
                        "severity": "WARNING",
                        "file_name": file_name,
                        "new_columns": list(new_cols),
                        "missing_columns": list(missing_cols),
                        "message": f"Schema changed for {file_name}",
                    })
        
        return alerts
    
    def write_monitoring_log(self, ingestion_date: Optional[str] = None) -> None:
        """
        Write monitoring records to output.
        
        Args:
            ingestion_date: Date for partitioning
        """
        if ingestion_date is None:
            ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        if self.monitoring_records:
            # Convert to DataFrame
            records_df = pd.DataFrame(self.monitoring_records)
            
            # Write Parquet
            parquet_path = (
                settings.MONITORING_OUTPUT / f"monitoring_log_date={ingestion_date}.parquet"
            )
            write_parquet(records_df, parquet_path)
            
            logger.info(f"Wrote monitoring log: {len(records_df)} records")
        
        if self.alerts:
            # Write alerts
            alerts_df = pd.DataFrame(self.alerts)
            
            csv_path = settings.GOLD_OUTPUT / "monitoring_alerts.csv"
            write_csv(alerts_df, csv_path)
            
            logger.info(f"Generated {len(self.alerts)} alerts")


def run_monitoring(
    validation_summary_df: pd.DataFrame,
    quarantine_df: pd.DataFrame,
    gtfs_dfs: Dict[str, pd.DataFrame],
    calendar_df: Optional[pd.DataFrame] = None,
) -> Dict:
    """
    Run the complete monitoring pipeline.
    
    Args:
        validation_summary_df: Validation summary
        quarantine_df: Quarantine records
        gtfs_dfs: GTFS DataFrames
        calendar_df: Optional calendar data for staleness check
        
    Returns:
        Monitoring results dictionary
    """
    monitor = MonitoringLayer()
    
    # Compute current metrics
    current_metrics = monitor.compute_quality_metrics(
        validation_summary_df,
        quarantine_df,
        gtfs_dfs,
    )
    
    monitor.monitoring_records.append(current_metrics)
    
    # Check for feed staleness
    if calendar_df is not None and len(calendar_df) > 0:
        staleness_alerts = monitor.detect_feed_staleness(calendar_df)
        monitor.alerts.extend(staleness_alerts)
    
    # Write monitoring artifacts
    ingestion_date = monitor.ingestion_timestamp.strftime("%Y-%m-%d")
    monitor.write_monitoring_log(ingestion_date)
    
    return {
        "metrics": current_metrics,
        "alerts": monitor.alerts,
    }
