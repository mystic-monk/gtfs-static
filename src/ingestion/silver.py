"""
Silver layer: Cleaned and conformed GTFS data.

Receives only records that passed all CRITICAL rules.
Apply transformations: standardise column types, resolve nulls, deduplicate,
and join related entities.
"""
import pandas as pd
import logging
from typing import Dict, Optional
from datetime import datetime

from src.config import settings
from src.utils.logging import setup_logging, log_layer_transition
from src.utils.file_io import write_parquet, read_parquet
from src.utils.date_utils import parse_gtfs_date, parse_gtfs_time

logger = setup_logging(__name__)


class SilverLayer:
    """
    Silver layer for cleaned and conformed GTFS data.
    """
    
    def __init__(self):
        self.ingestion_timestamp = datetime.now()
        self.silver_dfs = {}
    
    def standardize_stops(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean stops.txt data.
        
        Args:
            df: Raw stops data
            
        Returns:
            Cleaned stops DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["stop_id"] = df["stop_id"].astype(str).str.strip()
        df["stop_code"] = df["stop_code"].fillna("")
        df["stop_name"] = df["stop_name"].astype(str).str.strip()
        df["stop_desc"] = df["stop_desc"].fillna("")
        df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
        df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
        
        # Deduplicate
        df = df.drop_duplicates(subset=["stop_id"], keep="first")
        
        logger.info(f"Standardized stops: {len(df)} records")
        return df
    
    def standardize_routes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean routes.txt data.
        
        Args:
            df: Raw routes data
            
        Returns:
            Cleaned routes DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["route_id"] = df["route_id"].astype(str).str.strip()
        df["agency_id"] = df["agency_id"].astype(str).str.strip()
        df["route_short_name"] = df["route_short_name"].fillna("") if "route_short_name" in df.columns else ""
        df["route_long_name"]  = df["route_long_name"].fillna("")  if "route_long_name"  in df.columns else ""
        df["route_desc"]       = df["route_desc"].fillna("")       if "route_desc"       in df.columns else ""
        df["route_type"] = pd.to_numeric(df["route_type"], errors="coerce")
        
        # Deduplicate
        df = df.drop_duplicates(subset=["route_id"], keep="first")
        
        logger.info(f"Standardized routes: {len(df)} records")
        return df
    
    def standardize_trips(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean trips.txt data.
        
        Args:
            df: Raw trips data
            
        Returns:
            Cleaned trips DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["trip_id"] = df["trip_id"].astype(str).str.strip()
        df["route_id"] = df["route_id"].astype(str).str.strip()
        df["service_id"] = df["service_id"].astype(str).str.strip()
        df["trip_headsign"] = df["trip_headsign"].fillna("") if "trip_headsign" in df.columns else ""
        df["direction_id"]  = pd.to_numeric(df.get("direction_id", 0), errors="coerce")
        df["shape_id"]      = df["shape_id"].fillna("") if "shape_id" in df.columns else ""
        
        # Deduplicate
        df = df.drop_duplicates(subset=["trip_id"], keep="first")
        
        logger.info(f"Standardized trips: {len(df)} records")
        return df
    
    def standardize_stop_times(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean stop_times.txt data.
        
        Args:
            df: Raw stop_times data
            
        Returns:
            Cleaned stop_times DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["trip_id"] = df["trip_id"].astype(str).str.strip()
        df["stop_id"] = df["stop_id"].astype(str).str.strip()
        df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce")
        # Vectorized: strip whitespace, keep HH:MM:SS as-is (GTFS allows hours >= 24)
        for col in ("arrival_time", "departure_time"):
            df[col] = (
                df[col].astype(str).str.strip()
                .where(df[col].notna() & (df[col].astype(str).str.strip() != "nan"), other=None)
            )
        df["stop_headsign"] = df["stop_headsign"].fillna("")
        df["pickup_type"] = pd.to_numeric(df["pickup_type"], errors="coerce").fillna(0)
        df["drop_off_type"] = pd.to_numeric(df["drop_off_type"], errors="coerce").fillna(0)
        
        logger.info(f"Standardized stop_times: {len(df)} records")
        return df
    
    def standardize_calendar(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean calendar.txt data.
        
        Args:
            df: Raw calendar data
            
        Returns:
            Cleaned calendar DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["service_id"] = df["service_id"].astype(str).str.strip()
        day_columns = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for col in day_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        
        df["start_date"] = pd.to_datetime(df["start_date"].astype(str), format="%Y%m%d", errors="coerce").dt.date
        df["end_date"]   = pd.to_datetime(df["end_date"].astype(str),   format="%Y%m%d", errors="coerce").dt.date
        
        # Deduplicate
        df = df.drop_duplicates(subset=["service_id"], keep="first")
        
        logger.info(f"Standardized calendar: {len(df)} records")
        return df
    
    def standardize_calendar_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean calendar_dates.txt data.
        
        Args:
            df: Raw calendar_dates data
            
        Returns:
            Cleaned calendar_dates DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["service_id"] = df["service_id"].astype(str).str.strip()
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce").dt.date
        df["exception_type"] = pd.to_numeric(df["exception_type"], errors="coerce")
        
        logger.info(f"Standardized calendar_dates: {len(df)} records")
        return df
    
    def standardize_shapes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean shapes.txt data.
        
        Args:
            df: Raw shapes data
            
        Returns:
            Cleaned shapes DataFrame
        """
        if len(df) == 0:
            return df
        
        df = df.copy()
        
        # Standardize column types
        df["shape_id"] = df["shape_id"].astype(str).str.strip()
        df["shape_pt_lat"] = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
        df["shape_pt_lon"] = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
        df["shape_pt_sequence"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
        
        logger.info(f"Standardized shapes: {len(df)} records")
        return df
    
    def standardize_agency(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and clean agency.txt data.
        
        Args:
            df: Raw agency data
            
        Returns:
            Cleaned agency DataFrame
        """
        df = df.copy()
        
        # Standardize column types
        df["agency_id"] = df["agency_id"].astype(str).str.strip()
        df["agency_name"] = df["agency_name"].astype(str).str.strip()
        df["agency_url"]      = df["agency_url"].fillna("") if "agency_url" in df.columns else ""
        df["agency_timezone"] = df["agency_timezone"].fillna("Europe/Dublin") if "agency_timezone" in df.columns else "Europe/Dublin"
        df["agency_lang"]     = df["agency_lang"].fillna("en") if "agency_lang" in df.columns else "en"
        df["agency_phone"]    = df["agency_phone"].fillna("") if "agency_phone" in df.columns else ""
        
        # Deduplicate
        df = df.drop_duplicates(subset=["agency_id"], keep="first")
        
        logger.info(f"Standardized agency: {len(df)} records")
        return df
    
    def enrich_stop_times(
        self,
        stop_times_df: pd.DataFrame,
        routes_df: pd.DataFrame,
        trips_df: pd.DataFrame,
        stops_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Enrich stop_times with route and trip metadata.
        
        Args:
            stop_times_df: Stop times data
            routes_df: Routes data
            trips_df: Trips data
            stops_df: Stops data
            
        Returns:
            Enriched stop_times DataFrame
        """
        df = stop_times_df.copy()
        
        # Join with trips
        if len(trips_df) > 0:
            df = df.merge(
                trips_df[["trip_id", "route_id", "service_id", "direction_id"]],
                on="trip_id",
                how="left",
            )
        
        # Join with routes
        if len(routes_df) > 0:
            df = df.merge(
                routes_df[["route_id", "route_short_name", "route_type"]],
                on="route_id",
                how="left",
            )
        
        # Join with stops
        if len(stops_df) > 0:
            df = df.merge(
                stops_df[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
                on="stop_id",
                how="left",
                suffixes=("", "_stop"),
            )
        
        logger.info(f"Enriched stop_times: {len(df)} records with route and stop metadata")
        return df
    
    def transform_gtfs_data(
        self,
        gtfs_dfs: Dict[str, pd.DataFrame],
    ) -> Dict[str, pd.DataFrame]:
        """
        Transform and standardize all GTFS data.
        
        Args:
            gtfs_dfs: Dictionary of raw DataFrames
            
        Returns:
            Dictionary of standardized DataFrames
        """
        silver_dfs = {}
        
        # Standardize each file type
        if "agency" in gtfs_dfs:
            silver_dfs["agency"] = self.standardize_agency(gtfs_dfs["agency"])
        
        if "stops" in gtfs_dfs:
            silver_dfs["stops"] = self.standardize_stops(gtfs_dfs["stops"])
        
        if "routes" in gtfs_dfs:
            silver_dfs["routes"] = self.standardize_routes(gtfs_dfs["routes"])
        
        if "trips" in gtfs_dfs:
            silver_dfs["trips"] = self.standardize_trips(gtfs_dfs["trips"])
        
        if "calendar" in gtfs_dfs:
            silver_dfs["calendar"] = self.standardize_calendar(gtfs_dfs["calendar"])
        
        if "calendar_dates" in gtfs_dfs:
            silver_dfs["calendar_dates"] = self.standardize_calendar_dates(gtfs_dfs["calendar_dates"])
        
        if "shapes" in gtfs_dfs:
            silver_dfs["shapes"] = self.standardize_shapes(gtfs_dfs["shapes"])
        
        if "stop_times" in gtfs_dfs:
            silver_dfs["stop_times"] = self.standardize_stop_times(gtfs_dfs["stop_times"])
            
            # Enrich stop_times if we have required tables
            if all(key in silver_dfs for key in ["routes", "trips", "stops"]):
                silver_dfs["stop_times"] = self.enrich_stop_times(
                    silver_dfs["stop_times"],
                    silver_dfs["routes"],
                    silver_dfs["trips"],
                    silver_dfs["stops"],
                )
        
        self.silver_dfs = silver_dfs
        
        # Log layer transition
        total_records = sum(len(df) for df in silver_dfs.values())
        log_layer_transition(
            logger,
            "Bronze",
            "Silver",
            total_records,
            total_records,
        )
        
        return silver_dfs
    
    def write_silver_data(
        self,
        ingestion_date: Optional[str] = None,
    ) -> None:
        """
        Write Silver layer data to Parquet files.
        
        Args:
            ingestion_date: Date for partitioning
        """
        if ingestion_date is None:
            ingestion_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        
        for file_name, df in self.silver_dfs.items():
            output_path = settings.SILVER_OUTPUT / f"{file_name}_ingestion_date={ingestion_date}.parquet"
            write_parquet(df, output_path)
            logger.info(f"Wrote {file_name} to Silver layer: {len(df)} records")


def transform_to_silver_layer(
    gtfs_dfs: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """
    Execute complete Silver layer transformation.
    
    Args:
        gtfs_dfs: Dictionary of Bronze layer DataFrames
        
    Returns:
        Dictionary of Silver layer DataFrames
    """
    silver = SilverLayer()
    silver_dfs = silver.transform_gtfs_data(gtfs_dfs)
    silver.write_silver_data()
    
    return silver_dfs
