"""
Main pipeline orchestrator for the Irish GTFS Analytics Platform.

Coordinates the execution of all layers: Bronze -> Quarantine -> Silver -> Gold -> Profiles.
"""
import logging
from typing import Dict, Optional
from pathlib import Path

from src.config import settings
from src.utils.logging import setup_logging, log_layer_transition
from src.ingestion.bronze import ingest_bronze_layer
from src.ingestion.silver import transform_to_silver_layer
from src.ingestion.gold import create_gold_layer
from src.validation.runner import run_validation_pipeline
from src.profiling.profiler import profile_gtfs_files
from src.remediation.engine import apply_remediation
from src.monitoring.monitor import run_monitoring

logger = setup_logging(__name__)


def run_full_pipeline(
    operators: Optional[Dict[str, str]] = None,
    auto_remediate: bool = False,
) -> Dict:
    """
    Execute the complete GTFS analytics pipeline.
    
    Args:
        operators: Optional dict of {operator_name: feed_url}
        auto_remediate: Whether to enable automatic remediation
        
    Returns:
        Pipeline execution results
    """
    logger.info("Starting Irish GTFS Analytics Pipeline")
    
    results = {
        "bronze": {},
        "validation": {},
        "silver": {},
        "gold": {},
        "profiling": {},
        "remediation": {},
        "monitoring": {},
        "success": False,
    }
    
    try:
        # ============= BRONZE LAYER =============
        logger.info("=== BRONZE LAYER: Raw Data Ingestion ===")
        bronze_dfs, manifest = ingest_bronze_layer(operators)
        results["bronze"] = {"manifest": manifest, "record_count": sum(len(df) for df in bronze_dfs.values())}
        
        if not bronze_dfs:
            logger.error("Bronze layer failed - no data ingested")
            return results
        
        # ============= VALIDATION & QUARANTINE =============
        logger.info("=== VALIDATION & QUARANTINE LAYER ===")
        validated_dfs, quarantine_df, validation_summary = run_validation_pipeline(
            bronze_dfs,
            operator_name=list(operators.keys())[0] if operators else None,
        )
        results["validation"] = {
            "quarantined_records": len(quarantine_df),
            "validation_summary": validation_summary.to_dict("records") if validation_summary is not None else [],
        }
        
        # ============= SILVER LAYER =============
        logger.info("=== SILVER LAYER: Cleaned Data ===")
        silver_dfs = transform_to_silver_layer(validated_dfs)
        results["silver"] = {"record_count": sum(len(df) for df in silver_dfs.values())}
        
        # ============= GOLD LAYER =============
        logger.info("=== GOLD LAYER: Analytics Aggregates ===")
        gold_tables = create_gold_layer(silver_dfs)
        results["gold"] = {"tables": list(gold_tables.keys())}
        
        # ============= PROFILING =============
        logger.info("=== PROFILING LAYER ===")
        record_counts = {}
        if validation_summary is not None:
            for _, row in validation_summary.iterrows():
                file_name = row["source_file"]
                if file_name not in record_counts:
                    record_counts[file_name] = {"valid": 0, "quarantined": 0, "warned": 0}
                
                if row["severity"] == "CRITICAL":
                    record_counts[file_name]["quarantined"] += row["violation_count"]
                elif row["severity"] == "WARNING":
                    record_counts[file_name]["warned"] += row["violation_count"]
                
                record_counts[file_name]["valid"] = row["total_rows"] - record_counts[file_name]["quarantined"]
        
        profile_summary = profile_gtfs_files(silver_dfs, record_counts)
        results["profiling"] = {"profile_summary": profile_summary.to_dict("records") if profile_summary is not None else []}
        
        # ============= REMEDIATION =============
        logger.info("=== REMEDIATION LAYER ===")
        if auto_remediate and len(quarantine_df) > 0:
            remediated_df, remediation_log = apply_remediation(quarantine_df, auto_remediate=True)
            results["remediation"] = {
                "remediated_records": len(remediation_log),
                "remediation_log": remediation_log.to_dict("records") if remediation_log is not None else [],
            }
        else:
            results["remediation"] = {"message": "Remediation disabled or no violations to remediate"}
        
        # ============= MONITORING =============
        logger.info("=== MONITORING LAYER ===")
        monitoring_results = run_monitoring(
            validation_summary,
            quarantine_df,
            silver_dfs,
            silver_dfs.get("calendar"),
        )
        results["monitoring"] = monitoring_results
        
        results["success"] = True
        logger.info("Pipeline execution completed successfully")
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        results["error"] = str(e)
    
    return results


if __name__ == "__main__":
    # Run the full pipeline
    results = run_full_pipeline(auto_remediate=settings.AUTO_REMEDIATE_ENABLED)
    
    if results["success"]:
        print("✅ Pipeline completed successfully!")
        print(f"📊 Ingested {results['bronze'].get('record_count', 0)} raw records")
        print(f"🔍 Found {results['validation'].get('quarantined_records', 0)} validation issues")
        print(f"📈 Created {len(results['gold'].get('tables', []))} analytics tables")
    else:
        print("❌ Pipeline failed!")
        if "error" in results:
            print(f"Error: {results['error']}")
