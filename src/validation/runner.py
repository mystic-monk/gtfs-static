"""
Validation runner for the Irish GTFS Analytics Platform.

Orchestrates the execution of validation rules across all GTFS data files.
"""
from typing import Dict, Optional, Tuple
import pandas as pd
import logging
from datetime import datetime
from pathlib import Path

from src.validation.rules import ALL_RULES, get_rules_by_severity, get_rules_by_source
from src.config import settings
from src.utils.logging import setup_logging, log_layer_transition
from src.utils.file_io import write_parquet, write_csv, read_parquet

logger = setup_logging(__name__)


class ValidationRunner:
    """
    Execute validation rules on GTFS data and generate validation artifacts.
    """
    
    def __init__(self):
        self.validation_summary = []
        self.quarantine_log = []
        self.issue_counts_by_rule = {}
        self.ingestion_timestamp = datetime.now()

    @staticmethod
    def _load_disabled_rules() -> set:
        from src.config import settings
        import json
        f = settings.OUTPUTS_ROOT / "disabled_rules.json"
        if f.exists():
            return set(json.loads(f.read_text()))
        return set()
    
    def validate_gtfs_data(
        self,
        gtfs_dfs: Dict[str, pd.DataFrame],
        source_file: Optional[str] = None,
        operator_name: Optional[str] = None,
    ) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
        """
        Validate GTFS data against all rules.
        
        Args:
            gtfs_dfs: Dictionary of DataFrames from GTFS files
            source_file: Optional specific file to validate
            operator_name: Name of the operator (for logging)
            
        Returns:
            Tuple of (validated_dfs, quarantine_df)
                - validated_dfs: DataFrames with passed records (includes warning-flagged)
                - quarantine_df: DataFrame with CRITICAL violations
        """
        quarantine_records = []
        validated_dfs = {}
        
        # Get list of rules to run
        if source_file:
            rules_to_run = get_rules_by_source(source_file)
        else:
            rules_to_run = ALL_RULES

        # Respect disabled rules persisted by the UI
        disabled_rules = self._load_disabled_rules()
        if disabled_rules:
            rules_to_run = [r for r in rules_to_run if r.rule_code not in disabled_rules]

        # Run each rule
        for rule in rules_to_run:
            logger.info(f"Running rule: {rule.rule_code} - {rule.description}")
            
            # Get the appropriate data frame (keys in gtfs_dfs omit the .txt extension)
            df_key = rule.source_file.replace(".txt", "")
            if df_key not in gtfs_dfs:
                logger.warning(f"File {rule.source_file} not found in input data")
                continue

            df = gtfs_dfs[df_key]
            
            # Resolve cross-file dependencies declared on the rule
            _FILE_TO_KWARG = {
                "agency.txt": "agency_df",
                "routes.txt": "routes_df",
                "trips.txt": "trips_df",
                "stops.txt": "stops_df",
                "stop_times.txt": "stop_times_df",
                "shapes.txt": "shapes_df",
                "calendar.txt": "calendar_df",
                "calendar_dates.txt": "calendar_dates_df",
            }
            extra_dfs = {}
            for required_file in rule.required_files:
                kwarg = _FILE_TO_KWARG.get(required_file)
                lookup_key = required_file.replace(".txt", "")
                if kwarg and lookup_key in gtfs_dfs:
                    extra_dfs[kwarg] = gtfs_dfs[lookup_key]
            
            # Run validation rule
            try:
                if extra_dfs:
                    failing_records = rule.validate(df, **extra_dfs)
                else:
                    failing_records = rule.validate(df)
            except Exception as e:
                logger.error(f"Error executing rule {rule.rule_code}: {e}")
                failing_records = pd.DataFrame()
            
            if len(failing_records) > 0:
                # Add violation metadata
                failing_records = failing_records.copy()
                failing_records["quarantine_reason"] = rule.description
                failing_records["rule_code"] = rule.rule_code
                failing_records["severity"] = rule.severity
                failing_records["source_file"] = rule.source_file
                failing_records["ingestion_timestamp"] = self.ingestion_timestamp
                
                # Track statistics
                violation_count = len(failing_records)
                total_rows = len(df)
                violation_pct = (violation_count / total_rows * 100) if total_rows > 0 else 0
                
                self.validation_summary.append({
                    "rule_code": rule.rule_code,
                    "description": rule.description,
                    "severity": rule.severity,
                    "source_file": rule.source_file,
                    "violation_count": violation_count,
                    "total_rows": total_rows,
                    "violation_pct": violation_pct,
                    "operator": operator_name,
                    "ingestion_timestamp": self.ingestion_timestamp,
                })
                
                # Separate CRITICAL from WARNING/INFO
                if rule.severity == "CRITICAL":
                    quarantine_records.append(failing_records)
                    logger.warning(
                        f"Rule {rule.rule_code}: {violation_count} CRITICAL violations found"
                    )
                else:
                    # Mark records with data quality flag for WARNING/INFO
                    if "data_quality_flag" not in failing_records.columns:
                        failing_records["data_quality_flag"] = True
                    
                    logger.info(
                        f"Rule {rule.rule_code}: {violation_count} {rule.severity} violations found"
                    )
        
        # Combine all critical violations into quarantine dataframe
        if quarantine_records:
            quarantine_df = pd.concat(quarantine_records, ignore_index=True)
        else:
            quarantine_df = pd.DataFrame()
        
        # Process each file to create validated output
        for file_name, df in gtfs_dfs.items():
            if len(quarantine_df) == 0:
                # No violations, all records pass
                validated_dfs[file_name] = df.copy()
            else:
                # Remove CRITICAL violations, keep the rest
                # source_file metadata uses .txt; gtfs_dfs keys do not
                quarantine_file = quarantine_df[
                    quarantine_df["source_file"] == f"{file_name}.txt"
                ]
                
                if len(quarantine_file) > 0:
                    # Identify which columns are original (not metadata)
                    orig_cols = [col for col in df.columns if col not in 
                                ["quarantine_reason", "rule_code", "severity", "source_file", "ingestion_timestamp"]]
                    
                    # Mark records for removal
                    quarantine_indices = quarantine_file.index.intersection(df.index)
                    validated_df = df.drop(quarantine_indices)
                    validated_dfs[file_name] = validated_df
                else:
                    validated_dfs[file_name] = df.copy()
        
        logger.info(f"Validation complete. {len(quarantine_df)} records quarantined")
        
        return validated_dfs, quarantine_df
    
    def write_validation_artifacts(
        self,
        quarantine_df: pd.DataFrame,
        ingestion_date: Optional[str] = None,
    ) -> None:
        """
        Write validation artifacts to output directories.
        
        Args:
            quarantine_df: DataFrame with quarantined records
            ingestion_date: Date for partitioning (YYYY-MM-DD format)
        """
        if ingestion_date is None:
            ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        # Write quarantine log
        if len(quarantine_df) > 0:
            quarantine_path = settings.QUARANTINE_OUTPUT / f"quarantine_date={ingestion_date}.parquet"
            write_parquet(quarantine_df, quarantine_path)
            logger.info(f"Wrote {len(quarantine_df)} quarantined records to {quarantine_path}")
        
        # Write validation summary
        if self.validation_summary:
            summary_df = pd.DataFrame(self.validation_summary)
            summary_path = settings.QUARANTINE_OUTPUT / f"validation_summary_date={ingestion_date}.parquet"
            write_parquet(summary_df, summary_path)
            
            # Also write as CSV for Power BI
            csv_path = settings.GOLD_OUTPUT / "validation_summary.csv"
            write_csv(summary_df, csv_path)
            logger.info(f"Wrote validation summary to {summary_path}")
    
    def get_validation_report(self) -> pd.DataFrame:
        """
        Get a summary report of all validation issues.
        
        Returns:
            DataFrame with validation summary
        """
        if not self.validation_summary:
            return pd.DataFrame()
        
        return pd.DataFrame(self.validation_summary)


def run_validation_pipeline(
    gtfs_dfs: Dict[str, pd.DataFrame],
    operator_name: Optional[str] = None,
) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """
    Run the complete validation pipeline.
    
    Args:
        gtfs_dfs: Dictionary of GTFS data frames
        operator_name: Optional operator name for logging
        
    Returns:
        Tuple of (validated_dfs, quarantine_df, validation_summary_df)
    """
    runner = ValidationRunner()
    validated_dfs, quarantine_df = runner.validate_gtfs_data(
        gtfs_dfs,
        operator_name=operator_name,
    )
    
    ingestion_date = runner.ingestion_timestamp.strftime("%Y-%m-%d")
    runner.write_validation_artifacts(quarantine_df, ingestion_date)
    
    summary_df = runner.get_validation_report()
    
    return validated_dfs, quarantine_df, summary_df
