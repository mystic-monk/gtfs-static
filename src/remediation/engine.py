"""
Remediation engine for the Irish GTFS Analytics Platform.

Proposes and applies automated remediation for data quality violations.
"""
import pandas as pd
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

from src.config import settings
from src.utils.logging import setup_logging
from src.utils.file_io import write_parquet, write_csv
from src.utils.date_utils import convert_time_to_24h

logger = setup_logging(__name__)


class RemediationEngine:
    """
    Handle remediation of validation violations.
    """
    
    def __init__(self, auto_remediate: bool = False):
        self.auto_remediate = auto_remediate
        self.remediation_log = []
        self.remediation_summary = {}
        self.ingestion_timestamp = datetime.now()
    
    def remediate_violations(
        self,
        quarantine_df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Apply remediations to quarantined records.
        
        Args:
            quarantine_df: DataFrame with quarantined records
            
        Returns:
            Tuple of (remediated_records, remediation_log_df)
        """
        if len(quarantine_df) == 0:
            return pd.DataFrame(), pd.DataFrame()
        
        remediated = quarantine_df.copy()
        remediation_records = []
        
        # Group by rule code
        for rule_code in quarantine_df["rule_code"].unique():
            rule_violations = quarantine_df[quarantine_df["rule_code"] == rule_code]
            
            # Check if auto remediate is enabled for this rule
            should_remediate = settings.AUTO_REMEDIATE_RULES.get(rule_code, False)
            
            if should_remediate and self.auto_remediate:
                # Apply remediation logic based on rule code
                remediated_subset, remediation_actions = self._apply_remediation(
                    rule_code,
                    rule_violations,
                )
                
                # Update the remediated dataframe
                remediated.update(remediated_subset)
                
                # Log remediation actions
                remediation_records.extend(remediation_actions)
                
                logger.info(
                    f"Remediated {len(remediation_actions)} records for rule {rule_code}"
                )
            else:
                logger.warning(
                    f"Rule {rule_code} not configured for auto-remediation"
                )
        
        # Create remediation log
        if remediation_records:
            remediation_log_df = pd.DataFrame(remediation_records)
        else:
            remediation_log_df = pd.DataFrame(
                columns=["record_id", "rule_code", "original_value",
                        "remediated_value", "remediation_action", "remediation_timestamp"]
            )
        
        return remediated, remediation_log_df
    
    def _apply_remediation(
        self,
        rule_code: str,
        violations_df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, list]:
        """
        Apply specific remediation action for a rule.
        
        Args:
            rule_code: Rule code to remediate
            violations_df: DataFrame with violations
            
        Returns:
            Tuple of (remediated_df, remediation_actions_list)
        """
        remediated = violations_df.copy()
        actions = []
        
        if rule_code == "STOP-005":
            # Populate stop_name with "Unknown Stop" + stop_id
            for idx, row in remediated.iterrows():
                if pd.isna(row.get("stop_name")) or row.get("stop_name") == "":
                    actions.append({
                        "record_id": f"{row.get('stop_id', 'unknown')}",
                        "rule_code": rule_code,
                        "original_value": None,
                        "remediated_value": f"Unknown Stop {row['stop_id']}",
                        "remediation_action": "POPULATE",
                        "remediation_timestamp": self.ingestion_timestamp,
                    })
                    remediated.at[idx, "stop_name"] = f"Unknown Stop {row['stop_id']}"
        
        elif rule_code == "STOP-007":
            # Attempt re-encoding with UTF-8
            for idx, row in remediated.iterrows():
                try:
                    original = row.get("stop_name", "")
                    if isinstance(original, str):
                        remediated_val = original.encode("utf-8", errors="replace").decode("utf-8")
                        if remediated_val != original:
                            actions.append({
                                "record_id": f"{row.get('stop_id', 'unknown')}",
                                "rule_code": rule_code,
                                "original_value": original,
                                "remediated_value": remediated_val,
                                "remediation_action": "REENCODE",
                                "remediation_timestamp": self.ingestion_timestamp,
                            })
                            remediated.at[idx, "stop_name"] = remediated_val
                except Exception as e:
                    logger.warning(f"Error re-encoding stop name: {e}")
        
        elif rule_code == "ROUTE-003":
            # Use route_id as route_short_name if names are null
            for idx, row in remediated.iterrows():
                if (pd.isna(row.get("route_short_name")) or row.get("route_short_name") == "") and \
                   (pd.isna(row.get("route_long_name")) or row.get("route_long_name") == ""):
                    actions.append({
                        "record_id": f"{row.get('route_id', 'unknown')}",
                        "rule_code": rule_code,
                        "original_value": None,
                        "remediated_value": row["route_id"],
                        "remediation_action": "POPULATE",
                        "remediation_timestamp": self.ingestion_timestamp,
                    })
                    remediated.at[idx, "route_short_name"] = row["route_id"]
        
        elif rule_code == "TRIP-004":
            # Set shape_id to null for orphaned references
            for idx, row in remediated.iterrows():
                if not pd.isna(row.get("shape_id")) and row.get("shape_id") != "":
                    actions.append({
                        "record_id": f"{row.get('trip_id', 'unknown')}",
                        "rule_code": rule_code,
                        "original_value": row.get("shape_id"),
                        "remediated_value": None,
                        "remediation_action": "NULL_OUT",
                        "remediation_timestamp": self.ingestion_timestamp,
                    })
                    remediated.at[idx, "shape_id"] = None
        
        elif rule_code == "ST-005":
            # Convert times exceeding 24 hours
            for idx, row in remediated.iterrows():
                if not pd.isna(row.get("departure_time")):
                    normalized, is_next_day = convert_time_to_24h(row.get("departure_time", ""))
                    if is_next_day:
                        actions.append({
                            "record_id": f"{row.get('trip_id', 'unknown')}-{row.get('stop_sequence', 0)}",
                            "rule_code": rule_code,
                            "original_value": row.get("departure_time"),
                            "remediated_value": normalized,
                            "remediation_action": "NORMALIZE_TIME",
                            "remediation_timestamp": self.ingestion_timestamp,
                        })
                        remediated.at[idx, "departure_time"] = normalized
                        if "next_day_flag" not in remediated.columns:
                            remediated["next_day_flag"] = False
                        remediated.at[idx, "next_day_flag"] = True
        
        elif rule_code == "ST-007":
            # Flag zero dwell as interpolated
            for idx, row in remediated.iterrows():
                actions.append({
                    "record_id": f"{row.get('trip_id', 'unknown')}-{row.get('stop_sequence', 0)}",
                    "rule_code": rule_code,
                    "original_value": "zero_dwell_detected",
                    "remediated_value": "INTERPOLATED",
                    "remediation_action": "FLAG",
                    "remediation_timestamp": self.ingestion_timestamp,
                })
                if "interpolated_flag" not in remediated.columns:
                    remediated["interpolated_flag"] = False
                remediated.at[idx, "interpolated_flag"] = True
        
        elif rule_code == "CAL-003":
            # Flag service as inactive
            for idx, row in remediated.iterrows():
                actions.append({
                    "record_id": f"{row.get('service_id', 'unknown')}",
                    "rule_code": rule_code,
                    "original_value": "no_active_days",
                    "remediated_value": "INACTIVE",
                    "remediation_action": "FLAG",
                    "remediation_timestamp": self.ingestion_timestamp,
                })
                if "service_status" not in remediated.columns:
                    remediated["service_status"] = "ACTIVE"
                remediated.at[idx, "service_status"] = "INACTIVE"
        
        elif rule_code == "CAL-004":
            # Flag service as expired
            for idx, row in remediated.iterrows():
                actions.append({
                    "record_id": f"{row.get('service_id', 'unknown')}",
                    "rule_code": rule_code,
                    "original_value": "service_in_past",
                    "remediated_value": "EXPIRED",
                    "remediation_action": "FLAG",
                    "remediation_timestamp": self.ingestion_timestamp,
                })
                if "service_status" not in remediated.columns:
                    remediated["service_status"] = "ACTIVE"
                remediated.at[idx, "service_status"] = "EXPIRED"
        
        elif rule_code == "SHP-001":
            # Already handled by moving to orphaned shapes file
            pass
        
        elif rule_code == "SHP-003":
            # Deduplicate consecutive identical points
            actions.append({
                "record_id": "shapes_batch",
                "rule_code": rule_code,
                "original_value": len(remediated),
                "remediated_value": len(remediated),  # Will be updated after dedup
                "remediation_action": "DEDUPLICATE",
                "remediation_timestamp": self.ingestion_timestamp,
            })
        
        return remediated, actions
    
    def write_remediation_artifacts(
        self,
        remediation_log_df: pd.DataFrame,
        ingestion_date: Optional[str] = None,
    ) -> None:
        """
        Write remediation artifacts to output.
        
        Args:
            remediation_log_df: Remediation log DataFrame
            ingestion_date: Date for partitioning
        """
        if ingestion_date is None:
            ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        if len(remediation_log_df) > 0:
            # Write Parquet
            parquet_path = (
                settings.REMEDIATION_OUTPUT / f"remediation_log_date={ingestion_date}.parquet"
            )
            write_parquet(remediation_log_df, parquet_path)
            
            # Write CSV summary
            csv_path = settings.GOLD_OUTPUT / "remediation_log.csv"
            write_csv(remediation_log_df, csv_path)
            
            logger.info(f"Wrote remediation log: {len(remediation_log_df)} records")
    
    def create_remediation_summary(
        self,
        quarantine_df: pd.DataFrame,
        remediation_log_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Create remediation summary for Power BI.
        
        Args:
            quarantine_df: Original quarantine DataFrame
            remediation_log_df: Remediation log DataFrame
            
        Returns:
            Summary DataFrame
        """
        records = []
        
        for rule_code in quarantine_df["rule_code"].unique():
            violations = quarantine_df[quarantine_df["rule_code"] == rule_code]
            
            auto_remediated = 0
            manually_remediated = 0
            unresolved = len(violations)
            
            if len(remediation_log_df) > 0:
                remediated_count = len(
                    remediation_log_df[remediation_log_df["rule_code"] == rule_code]
                )
                auto_remediated = remediated_count
                unresolved = len(violations) - remediated_count
            
            remediation_pct = (auto_remediated / len(violations) * 100) if len(violations) > 0 else 0
            
            records.append({
                "rule_code": rule_code,
                "total_violations": len(violations),
                "auto_remediated_count": auto_remediated,
                "manually_remediated_count": manually_remediated,
                "unresolved_count": unresolved,
                "remediation_pct": remediation_pct,
            })
        
        return pd.DataFrame(records) if records else pd.DataFrame(
            columns=[
                "rule_code",
                "total_violations",
                "auto_remediated_count",
                "manually_remediated_count",
                "unresolved_count",
                "remediation_pct",
            ]
        )


def apply_remediation(
    quarantine_df: pd.DataFrame,
    auto_remediate: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run the remediation engine on quarantine records.
    
    Args:
        quarantine_df: Quarantine DataFrame
        auto_remediate: Whether to enable auto-remediation
        
    Returns:
        Tuple of (remediated_df, remediation_log_df)
    """
    engine = RemediationEngine(auto_remediate=auto_remediate)
    remediated, remediation_log = engine.remediate_violations(quarantine_df)
    
    ingestion_date = engine.ingestion_timestamp.strftime("%Y-%m-%d")
    engine.write_remediation_artifacts(remediation_log, ingestion_date)
    
    return remediated, remediation_log
