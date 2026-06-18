"""
Bronze layer: Raw GTFS data ingestion and storage.

Downloads GTFS static feeds and stores raw parsed DataFrames as Parquet files.
Apply no transformations. Preserve all original values including nulls and malformed data.
"""
import pandas as pd
import requests
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
import tempfile

from src.config import settings
from src.utils.logging import setup_logging, log_layer_transition
from src.utils.file_io import extract_gtfs_zip, write_parquet, read_parquet

logger = setup_logging(__name__)


class BronzeLayer:
    """
    Bronze layer for raw GTFS data ingestion.
    """
    
    def __init__(self):
        self.ingestion_timestamp = datetime.now()
        self.operator_data = {}
    
    def download_gtfs_feed(self, operator_name: str, feed_url: str) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Download and parse a GTFS feed from a URL.
        Falls back to sample data if real feeds are not available.
        
        Args:
            operator_name: Name of the operator
            feed_url: URL to the GTFS zip file
            
        Returns:
            Dictionary mapping filename (without .txt) to DataFrame, or None if failed
        """
        try:
            logger.info(f"Downloading GTFS feed for {operator_name} from {feed_url}")

            # Extract zip to temporary directory
            with tempfile.TemporaryDirectory() as tmpdir:
                tmppath = Path(tmpdir)
                zip_path = tmppath / "feed.zip"

                # Stream the download straight to disk in chunks — avoids holding
                # the entire zip body in memory via response.content (matters on
                # memory-constrained hosts; the combined feed can be tens of MB).
                with requests.get(feed_url, timeout=30, stream=True) as response:
                    response.raise_for_status()
                    with open(zip_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)

                # Extract GTFS files
                gtfs_dfs = extract_gtfs_zip(zip_path, tmppath)
                self._apply_sample_size(gtfs_dfs)

                logger.info(f"Successfully downloaded and extracted GTFS feed for {operator_name}")
                return gtfs_dfs

        except requests.RequestException as e:
            logger.error(f"Failed to download GTFS feed for {operator_name}: {e}")
            logger.info(f"Attempting to use sample data instead...")
            return self._load_sample_data()
        except Exception as e:
            logger.error(f"Error processing GTFS feed for {operator_name}: {e}")
            return None

    @staticmethod
    def _apply_sample_size(gtfs_dfs: Dict[str, pd.DataFrame]) -> None:
        """
        Cap the largest fact tables at settings.SAMPLE_SIZE rows, in place.

        Only stop_times and shapes are truncated — they dominate memory in a
        country-wide combined feed. Dimension tables (agency, routes, trips,
        stops, calendar) are left intact so referential integrity holds; a
        truncated stop_times simply joins against fewer rows, it doesn't
        orphan anything. Intended as a low-memory dial for constrained hosts
        (e.g. Render's free 512Mi tier) — set SAMPLE_SIZE in the environment.
        """
        if not settings.SAMPLE_SIZE:
            return
        for key in ("stop_times", "shapes"):
            df = gtfs_dfs.get(key)
            if df is not None and len(df) > settings.SAMPLE_SIZE:
                logger.info(
                    f"SAMPLE_SIZE={settings.SAMPLE_SIZE} set — truncating {key} from {len(df)} rows"
                )
                gtfs_dfs[key] = df.iloc[: settings.SAMPLE_SIZE].copy()

    def _load_sample_data(self) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Load sample GTFS data for testing when real feeds are not available.
        
        Returns:
            Dictionary of sample GTFS DataFrames
        """
        try:
            from src.ingestion.sample_data import (
                generate_stops_df,
                generate_routes_df,
                generate_calendar_df,
                generate_calendar_dates_df,
                generate_agency_df,
                generate_trips_and_stop_times,
            )
            
            logger.info("Loading sample GTFS data for testing")
            
            stops_df = generate_stops_df()
            routes_df = generate_routes_df()
            calendar_df = generate_calendar_df()
            calendar_dates_df = generate_calendar_dates_df()
            agency_df = generate_agency_df()
            trips_df, stop_times_df = generate_trips_and_stop_times()
            
            return {
                "agency": agency_df,
                "stops": stops_df,
                "routes": routes_df,
                "calendar": calendar_df,
                "calendar_dates": calendar_dates_df,
                "trips": trips_df,
                "stop_times": stop_times_df,
            }
        except Exception as e:
            logger.error(f"Failed to load sample data: {e}")
            return None
    
    def ingest_operator_data(
        self,
        operator_name: str,
        gtfs_dfs: Dict[str, pd.DataFrame],
    ) -> None:
        """
        Store raw GTFS data for an operator in the Bronze layer.
        
        Args:
            operator_name: Name of the operator
            gtfs_dfs: Dictionary of raw DataFrames
        """
        ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        for file_name, df in gtfs_dfs.items():
            # Add metadata columns
            df_with_meta = df.copy()
            df_with_meta["operator"] = operator_name
            df_with_meta["ingestion_date"] = ingestion_date
            df_with_meta["ingestion_timestamp"] = self.ingestion_timestamp
            
            # Write to partitioned Parquet
            output_path = (
                settings.BRONZE_OUTPUT 
                / file_name 
                / f"operator={operator_name}"
                / f"ingestion_date={ingestion_date}"
                / "data.parquet"
            )
            
            write_parquet(df_with_meta, output_path)
            logger.info(
                f"Ingested {file_name} for {operator_name}: {len(df)} rows"
            )
        
        self.operator_data[operator_name] = gtfs_dfs
    
    def read_bronze_data(
        self,
        file_name: str,
        operator_name: Optional[str] = None,
        ingestion_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Read Bronze layer data.
        
        Args:
            file_name: Name of the GTFS file (e.g., 'stops', 'routes')
            operator_name: Optional operator to filter by
            ingestion_date: Optional date to filter by
            
        Returns:
            Combined DataFrame from matching files
        """
        dfs = []
        
        bronze_path = settings.BRONZE_OUTPUT / file_name
        if not bronze_path.exists():
            logger.warning(f"Bronze path does not exist: {bronze_path}")
            return pd.DataFrame()
        
        # Find all matching parquet files
        parquet_files = list(bronze_path.glob("**/data.parquet"))
        
        for parquet_file in parquet_files:
            # Check operator and date filters
            if operator_name and f"operator={operator_name}" not in str(parquet_file):
                continue
            
            if ingestion_date and f"ingestion_date={ingestion_date}" not in str(parquet_file):
                continue
            
            try:
                df = read_parquet(parquet_file)
                dfs.append(df)
            except Exception as e:
                logger.warning(f"Error reading {parquet_file}: {e}")
        
        if dfs:
            combined_df = pd.concat(dfs, ignore_index=True)
            logger.info(f"Read {len(combined_df)} rows from {file_name}")
            return combined_df
        
        return pd.DataFrame()
    
    def get_ingestion_manifest(self) -> Dict:
        """
        Get summary of what was ingested.
        
        Returns:
            Manifest dictionary with operator data summaries
        """
        manifest = {
            "ingestion_timestamp": self.ingestion_timestamp.isoformat(),
            "operators": {},
        }
        
        for operator_name, gtfs_dfs in self.operator_data.items():
            manifest["operators"][operator_name] = {
                "files": {
                    file_name: {
                        "row_count": len(df),
                        "column_count": len(df.columns),
                    }
                    for file_name, df in gtfs_dfs.items()
                }
            }
        
        return manifest


def ingest_bronze_layer(
    operators: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, pd.DataFrame], Dict]:
    """
    Execute the Bronze layer ingestion from the combined TFI GTFS_All feed.

    Args:
        operators: Ignored — retained for interface compatibility. The combined
                   feed URL from config is always used.

    Returns:
        Tuple of (gtfs_dfs, manifest)
    """
    bronze = BronzeLayer()

    feed_url = settings.GTFS_ALL_FEED_URL
    gtfs_dfs = bronze.download_gtfs_feed("all_operators", feed_url)

    if not gtfs_dfs:
        logger.error("Bronze layer failed — no data ingested")
        return {}, bronze.get_ingestion_manifest()

    bronze.ingest_operator_data("all_operators", gtfs_dfs)

    total_records = sum(len(df) for df in gtfs_dfs.values())
    log_layer_transition(logger, "Ingestion", "Bronze", total_records, total_records)

    return gtfs_dfs, bronze.get_ingestion_manifest()
