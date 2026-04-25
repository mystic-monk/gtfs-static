#!/usr/bin/env python
"""
Simplified pipeline test - Bronze to Gold layers only.
Good for testing without running the full pipeline.
"""
import sys
from pathlib import Path
from src.config import settings
from src.utils.logging import setup_logging
from src.ingestion.bronze import ingest_bronze_layer
from src.ingestion.silver import transform_to_silver_layer
from src.ingestion.gold import create_gold_layer
from src.ingestion.sample_data import create_sample_gtfs_zip

logger = setup_logging(__name__)

def test_pipeline():
    """Run a simplified test pipeline."""
    logger.info("[START] Starting simplified test pipeline...")
    
    try:
        # Step 1: Create sample data
        logger.info("\n[STEP1] Generating sample GTFS data...")
        sample_zip = Path("outputs/sample_dublin_bus.zip")
        create_sample_gtfs_zip(sample_zip)
        logger.info(f"[OK] Sample data created: {sample_zip}")
        
        # Step 2: Bronze layer
        logger.info("\n[STEP2] Bronze Layer - Raw data ingestion...")
        operators = {
            "dublin_bus": str(sample_zip),  # Use local sample zip
        }
        bronze_dfs, manifest = ingest_bronze_layer(operators)
        logger.info(f"[OK] Bronze complete: {len(bronze_dfs)} files ingested")
        for file_name, df in bronze_dfs.items():
            logger.info(f"   - {file_name}: {len(df)} rows")
        
        if not bronze_dfs:
            logger.error("[ERROR] Bronze layer produced no data")
            return False
        
        # Step 3: Silver layer
        logger.info("\n[STEP3] Silver Layer - Data cleaning...")
        silver_dfs = transform_to_silver_layer(bronze_dfs)
        logger.info(f"[OK] Silver complete: {len(silver_dfs)} files")
        for file_name, df in silver_dfs.items():
            logger.info(f"   - {file_name}: {len(df)} rows")
        
        # Step 4: Gold layer
        logger.info("\n[STEP4] Gold Layer - Analytics tables...")
        gold_tables = create_gold_layer(silver_dfs)
        logger.info(f"[OK] Gold complete: {len(gold_tables)} analytics tables")
        for table_name, df in gold_tables.items():
            logger.info(f"   - {table_name}: {len(df)} rows")
        
        logger.info("\n" + "="*60)
        logger.info("[COMPLETE] Pipeline test completed successfully!")
        logger.info("="*60)
        logger.info("\nNext steps:")
        logger.info("1. Run the full pipeline: python -m src.ingestion.pipeline")
        logger.info("2. Launch the dashboard: python -m streamlit run src/dashboard/app.py")
        logger.info("3. Start the API: python -m uvicorn src.api.main:app --reload")
        
        return True
        
    except Exception as e:
        logger.error(f"[ERROR] Pipeline test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_pipeline()
    sys.exit(0 if success else 1)