"""
Data profiling engine for the Irish GTFS Analytics Platform.

Computes statistical profiles for every GTFS source file and column.
"""
import pandas as pd
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

from src.config import settings
from src.utils.logging import setup_logging
from src.utils.file_io import write_parquet, write_csv

logger = setup_logging(__name__)


class DataProfiler:
    """
    Compute and store data profiles for GTFS files.
    """
    
    def __init__(self):
        self.profiles = {}
        self.ingestion_timestamp = datetime.now()
    
    def profile_dataframe(
        self,
        df: pd.DataFrame,
        file_name: str,
        valid_records: int = None,
        quarantined_records: int = None,
        warning_flagged_records: int = None,
    ) -> Dict[str, Any]:
        """
        Compute comprehensive profile for a DataFrame.
        
        Args:
            df: DataFrame to profile
            file_name: Name of the source file (e.g., 'stops', 'routes')
            valid_records: Count of valid records
            quarantined_records: Count of CRITICAL violations
            warning_flagged_records: Count of WARNING violations
            
        Returns:
            Profile dictionary
        """
        profile = {
            "file_name": file_name,
            "timestamp": self.ingestion_timestamp.isoformat(),
            "row_counts": {
                "total_rows": len(df),
                "valid_rows": valid_records or len(df),
                "quarantined_rows": quarantined_records or 0,
                "warning_flagged_rows": warning_flagged_records or 0,
            },
            "columns": {},
        }
        
        # Profile each column
        for col in df.columns:
            col_profile = self._profile_column(df[col], col)
            profile["columns"][col] = col_profile
        
        return profile
    
    def _profile_column(self, series: pd.Series, col_name: str) -> Dict[str, Any]:
        """
        Compute statistics for a single column.
        
        Args:
            series: Data column
            col_name: Column name
            
        Returns:
            Column profile dictionary
        """
        col_profile = {
            "name": col_name,
            "data_type": str(series.dtype),
            "null_count": int(series.isna().sum()),
            "null_pct": float(series.isna().sum() / len(series) * 100) if len(series) > 0 else 0,
            "distinct_count": int(series.nunique()),
            "cardinality_flags": [],
        }
        
        # Determine cardinality flags
        total_count = len(series)
        distinct_count = series.nunique()
        
        if distinct_count == total_count:
            col_profile["cardinality_flags"].append("candidate_key")
        
        if distinct_count == 1:
            col_profile["cardinality_flags"].append("constant_column")
        
        if col_profile["null_pct"] > 20:
            col_profile["cardinality_flags"].append("mostly_null")
        
        # Try to parse as numeric
        try:
            numeric_series = pd.to_numeric(series, errors="coerce")
            if numeric_series.notna().sum() > 0:  # At least some numeric values
                col_profile["numeric_stats"] = {
                    "min_value": float(numeric_series.min()),
                    "max_value": float(numeric_series.max()),
                    "mean": float(numeric_series.mean()),
                    "median": float(numeric_series.median()),
                    "std_dev": float(numeric_series.std()),
                    "percentile_5": float(numeric_series.quantile(0.05)),
                    "percentile_95": float(numeric_series.quantile(0.95)),
                }
        except (ValueError, TypeError):
            pass
        
        # String-specific statistics
        try:
            if series.dtype == "object" or series.dtype == "string":
                # Top 10 most frequent values (keys must be strings for JSON)
                top_values = series.value_counts().head(10)
                col_profile["top_10_values"] = {str(k): int(v) for k, v in top_values.items()}
                
                # Encoding issues (non-ASCII characters)
                encoding_issues = series.astype(str).apply(
                    lambda x: any(ord(c) > 127 for c in x)
                )
                
                if encoding_issues.sum() > 0:
                    col_profile["encoding_issue_count"] = int(encoding_issues.sum())
                    col_profile["encoding_issue_pct"] = float(
                        encoding_issues.sum() / len(series) * 100
                    )
                    
                    # Example values with encoding issues
                    examples = series[encoding_issues].head(5).tolist()
                    col_profile["encoding_issue_examples"] = [str(e) for e in examples]
        except Exception as e:
            logger.warning(f"Error profiling string column {col_name}: {e}")
        
        return col_profile
    
    def profile_gtfs_data(
        self,
        gtfs_dfs: Dict[str, pd.DataFrame],
        record_counts: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Profile all GTFS dataframes.
        
        Args:
            gtfs_dfs: Dictionary of DataFrames
            record_counts: Optional dict with validation record counts per file
            
        Returns:
            Dictionary mapping filename to profile
        """
        profiles = {}
        
        for file_name, df in gtfs_dfs.items():
            counts = record_counts.get(file_name, {}) if record_counts else {}
            
            profile = self.profile_dataframe(
                df,
                file_name,
                valid_records=counts.get("valid"),
                quarantined_records=counts.get("quarantined"),
                warning_flagged_records=counts.get("warned"),
            )
            
            profiles[file_name] = profile
            self.profiles[file_name] = profile
            logger.info(f"Profiled {file_name}: {len(df)} rows, {len(df.columns)} columns")
        
        return profiles
    
    def write_profiles(
        self,
        ingestion_date: Optional[str] = None,
    ) -> None:
        """
        Write profiles as JSON and Parquet files.
        
        Args:
            ingestion_date: Date for partitioning (YYYY-MM-DD format)
        """
        if ingestion_date is None:
            ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        # Convert profiles to flat format for Parquet
        profile_records = []
        
        for file_name, profile in self.profiles.items():
            # Row count summary
            row_count_record = {
                "file_name": file_name,
                "ingestion_date": ingestion_date,
                "metric_type": "row_counts",
                "total_rows": profile["row_counts"]["total_rows"],
                "valid_rows": profile["row_counts"]["valid_rows"],
                "quarantined_rows": profile["row_counts"]["quarantined_rows"],
                "warning_flagged_rows": profile["row_counts"]["warning_flagged_rows"],
            }
            profile_records.append(row_count_record)
            
            # Column-level statistics
            for col_name, col_profile in profile["columns"].items():
                col_record = {
                    "file_name": file_name,
                    "ingestion_date": ingestion_date,
                    "column_name": col_name,
                    "metric_type": "column_stats",
                    "data_type": col_profile["data_type"],
                    "null_count": col_profile["null_count"],
                    "null_pct": col_profile["null_pct"],
                    "distinct_count": col_profile["distinct_count"],
                    "cardinality_flags": json.dumps(col_profile["cardinality_flags"]),
                }
                
                # Add numeric stats if available
                if "numeric_stats" in col_profile:
                    stats = col_profile["numeric_stats"]
                    col_record.update({
                        "min_value": stats["min_value"],
                        "max_value": stats["max_value"],
                        "mean": stats["mean"],
                        "median": stats["median"],
                        "std_dev": stats["std_dev"],
                        "percentile_5": stats["percentile_5"],
                        "percentile_95": stats["percentile_95"],
                    })
                
                # Add encoding issues if present
                if "encoding_issue_count" in col_profile:
                    col_record["encoding_issue_count"] = col_profile["encoding_issue_count"]
                    col_record["encoding_issue_pct"] = col_profile["encoding_issue_pct"]
                
                profile_records.append(col_record)
        
        # Write as Parquet
        if profile_records:
            profile_df = pd.DataFrame(profile_records)
            parquet_path = settings.PROFILES_OUTPUT / f"profile_date={ingestion_date}.parquet"
            write_parquet(profile_df, parquet_path)
            logger.info(f"Wrote profile data to {parquet_path}")
        
        # Write JSON files per file for archival
        for file_name, profile in self.profiles.items():
            json_path = settings.PROFILES_OUTPUT / f"{file_name}_profile_{ingestion_date}.json"
            with open(json_path, "w") as f:
                json.dump(profile, f, indent=2, default=str)
            logger.info(f"Wrote profile JSON to {json_path}")
    
    def get_profile_summary(self) -> pd.DataFrame:
        """
        Get a flattened summary of all profiles suitable for Power BI.
        
        Returns:
            DataFrame with column-level statistics
        """
        records = []
        
        for file_name, profile in self.profiles.items():
            for col_name, col_profile in profile["columns"].items():
                record = {
                    "file_name": file_name,
                    "column_name": col_name,
                    "data_type": col_profile["data_type"],
                    "null_pct": col_profile["null_pct"],
                    "distinct_count": col_profile["distinct_count"],
                }
                
                # Add numeric stats
                if "numeric_stats" in col_profile:
                    stats = col_profile["numeric_stats"]
                    record.update({
                        "min_value": stats.get("min_value"),
                        "max_value": stats.get("max_value"),
                        "mean": stats.get("mean"),
                        "median": stats.get("median"),
                    })
                
                records.append(record)
        
        return pd.DataFrame(records) if records else pd.DataFrame()


def profile_gtfs_files(
    gtfs_dfs: Dict[str, pd.DataFrame],
    record_counts: Optional[Dict[str, Dict]] = None,
) -> pd.DataFrame:
    """
    Profile all GTFS files and return summary as DataFrame.
    
    Args:
        gtfs_dfs: Dictionary of DataFrames
        record_counts: Optional record count statistics
        
    Returns:
        Profile summary DataFrame
    """
    profiler = DataProfiler()
    profiler.profile_gtfs_data(gtfs_dfs, record_counts)
    profiler.write_profiles()
    
    return profiler.get_profile_summary()
