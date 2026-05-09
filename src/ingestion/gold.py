"""
Gold layer: Aggregated and analytics-ready outputs.

Produces named aggregate tables as both Parquet and CSV files for Power BI consumption.
"""
import pandas as pd
import logging
from typing import Dict, Optional
from datetime import datetime

from src.config import settings
from src.utils.logging import setup_logging, log_layer_transition
from src.utils.file_io import write_parquet, write_csv
from src.utils.date_utils import get_active_service_dates, format_gtfs_date

logger = setup_logging(__name__)

_DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _service_days_series(calendar_df: pd.DataFrame) -> "pd.Series":
    """Return active-day count per row in calendar_df (same index). Avoids repeated apply()."""
    return calendar_df.apply(
        lambda r: get_active_service_dates(
            r["start_date"], r["end_date"],
            {d: r.get(d, 0) for d in _DOW},
        ),
        axis=1,
    )


class GoldLayer:
    """
    Gold layer for aggregated analytics-ready data.
    """
    
    def __init__(self):
        self.ingestion_timestamp = datetime.now()
        self.gold_tables = {}
    
    def create_route_summary(
        self,
        routes_df: pd.DataFrame,
        trips_df: pd.DataFrame,
        stop_times_df: pd.DataFrame,
        calendar_df: pd.DataFrame,
        agency_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Create route_summary table.
        """
        routes_df = routes_df.copy()

        # Join agency_name from agency.txt — agency_id in routes.txt is often a numeric key
        if agency_df is not None and "agency_id" in routes_df.columns and "agency_id" in agency_df.columns:
            name_map = agency_df.set_index("agency_id")["agency_name"].to_dict()
            routes_df["agency_name"] = routes_df["agency_id"].map(name_map).fillna(routes_df.get("agency_id", "Unknown"))
        elif "agency_name" not in routes_df.columns:
            routes_df["agency_name"] = routes_df.get("agency_id", "Unknown")
        
        # Count trips per route
        trip_counts = trips_df.groupby("route_id").size().reset_index(name="total_trips")
        
        # Count unique stops per route
        stop_counts = (
            stop_times_df.groupby("route_id")["stop_id"]
            .nunique()
            .reset_index(name="total_stops")
        )
        
        # Count active service days per route
        cal_days = calendar_df.copy()
        cal_days["_service_days"] = _service_days_series(calendar_df)
        route_services = (
            trips_df[["route_id", "service_id"]]
            .drop_duplicates()
            .merge(cal_days[["service_id", "_service_days"]], on="service_id", how="left")
        )
        service_days = (
            route_services.groupby("route_id")["_service_days"]
            .sum()
            .reset_index(name="service_days")
        )
        
        # Combine all metrics
        base_cols = ["route_id", "agency_name", "route_short_name", "route_long_name"]
        if "route_type" in routes_df.columns:
            base_cols.append("route_type")
        summary = routes_df[base_cols].copy()
        summary = summary.merge(trip_counts, on="route_id", how="left")
        summary = summary.merge(stop_counts, on="route_id", how="left")
        summary = summary.merge(service_days, on="route_id", how="left")
        
        summary = summary.fillna(0)
        summary["total_trips"] = summary["total_trips"].astype(int)
        summary["total_stops"] = summary["total_stops"].astype(int)
        summary["service_days"] = summary["service_days"].astype(int)
        
        logger.info(f"Created route_summary: {len(summary)} routes")
        return summary
    
    def create_stop_activity(
        self,
        stops_df: pd.DataFrame,
        stop_times_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Create stop_activity table.
        
        stop_id, stop_name, latitude, longitude, total_departures, unique_routes, peak_hour_departures
        """
        activity = stops_df[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy()
        activity.columns = ["stop_id", "stop_name", "latitude", "longitude"]
        
        # Count departures per stop
        departures = (
            stop_times_df[stop_times_df["departure_time"].notna()]
            .groupby("stop_id")
            .size()
            .reset_index(name="total_departures")
        )
        
        # Count unique routes per stop
        unique_routes = (
            stop_times_df.groupby("stop_id")["route_id"]
            .nunique()
            .reset_index(name="unique_routes")
        )
        
        # Peak hour departures (7-9 AM and 5-7 PM) — vectorized
        _hours = (
            stop_times_df["departure_time"]
            .astype(str)
            .str.split(":", n=1)
            .str[0]
            .str.extract(r"^(\d+)$", expand=False)
            .astype(float, errors="ignore")
        )
        peak_times = stop_times_df[_hours.isin([7.0, 8.0, 17.0, 18.0])]
        peak_departures = (
            peak_times.groupby("stop_id")
            .size()
            .reset_index(name="peak_hour_departures")
        )
        
        # Combine metrics
        activity = activity.merge(departures, on="stop_id", how="left")
        activity = activity.merge(unique_routes, on="stop_id", how="left")
        activity = activity.merge(peak_departures, on="stop_id", how="left")
        
        activity = activity.fillna(0)
        activity["total_departures"] = activity["total_departures"].astype(int)
        activity["unique_routes"] = activity["unique_routes"].astype(int)
        activity["peak_hour_departures"] = activity["peak_hour_departures"].astype(int)
        
        logger.info(f"Created stop_activity: {len(activity)} stops")
        return activity
    
    def create_operator_summary(
        self,
        agency_df: pd.DataFrame,
        routes_df: pd.DataFrame,
        trips_df: pd.DataFrame,
        calendar_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Create operator_summary table.
        
        agency_id, agency_name, total_routes, total_trips, active_service_days
        """
        summary = agency_df[["agency_id", "agency_name"]].copy()
        
        # Count routes per agency
        route_counts = routes_df.groupby("agency_id").size().reset_index(name="total_routes")
        
        # Count trips per agency
        trips_by_agency = (
            trips_df.merge(routes_df[["route_id", "agency_id"]], on="route_id")
            .groupby("agency_id")
            .size()
            .reset_index(name="total_trips")
        )
        
        service_days = calendar_df[["service_id"]].copy()
        service_days["active_days"] = _service_days_series(calendar_df)
        
        # Link services to agencies through trips and routes
        trips_with_agency = trips_df.merge(
            routes_df[["route_id", "agency_id"]],
            on="route_id"
        )[["agency_id", "service_id"]].drop_duplicates()
        
        service_by_agency = (
            trips_with_agency.merge(
                service_days.rename(columns={"service_id": "service_id", "active_days": "days"}),
                on="service_id"
            )
            .groupby("agency_id")["days"]
            .sum()
            .reset_index(name="active_service_days")
        )
        
        # Combine
        summary = summary.merge(route_counts, on="agency_id", how="left")
        summary = summary.merge(trips_by_agency, on="agency_id", how="left")
        summary = summary.merge(service_by_agency, on="agency_id", how="left")
        
        summary = summary.fillna(0)
        summary["total_routes"] = summary["total_routes"].astype(int)
        summary["total_trips"] = summary["total_trips"].astype(int)
        summary["active_service_days"] = summary["active_service_days"].astype(int)
        
        logger.info(f"Created operator_summary: {len(summary)} operators")
        return summary
    
    def create_headway_analysis(
        self,
        stop_times_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Create headway_analysis table — fully vectorized.

        Headway = gap in minutes between consecutive departures at the same stop
        for the same (route, direction) combination.
        """
        _EMPTY = pd.DataFrame(columns=[
            "route_id", "direction_id", "avg_headway_minutes",
            "min_headway_minutes", "max_headway_minutes",
        ])

        required = {"route_id", "stop_id", "departure_time"}
        if not required.issubset(stop_times_df.columns):
            logger.warning("create_headway_analysis: missing required columns, skipping")
            return _EMPTY

        try:
            df = stop_times_df[["route_id", "stop_id", "departure_time"]].copy()
            if "direction_id" in stop_times_df.columns:
                df["direction_id"] = stop_times_df["direction_id"].fillna(0).astype(int)
            else:
                df["direction_id"] = 0

            # Convert GTFS time strings (may exceed 24h) to integer seconds
            parts = df["departure_time"].astype(str).str.split(":", expand=True)
            df["_secs"] = (
                pd.to_numeric(parts[0], errors="coerce") * 3600
                + pd.to_numeric(parts[1], errors="coerce") * 60
                + pd.to_numeric(parts[2], errors="coerce")
            )
            df = df.dropna(subset=["_secs"])

            # Sort and compute gap to previous departure at same (route, direction, stop)
            df = df.sort_values(["route_id", "direction_id", "stop_id", "_secs"])
            df["_prev"] = df.groupby(["route_id", "direction_id", "stop_id"])["_secs"].shift(1)
            df["_gap_min"] = (df["_secs"] - df["_prev"]) / 60

            valid = df[(df["_gap_min"] > 0) & df["_gap_min"].notna()]

            headway_df = (
                valid.groupby(["route_id", "direction_id"])["_gap_min"]
                .agg(avg_headway_minutes="mean", min_headway_minutes="min", max_headway_minutes="max")
                .reset_index()
            )

            headway_df[["avg_headway_minutes", "min_headway_minutes", "max_headway_minutes"]] = (
                headway_df[["avg_headway_minutes", "min_headway_minutes", "max_headway_minutes"]].round(1)
            )

            logger.info(f"Created headway_analysis: {len(headway_df)} records")
            return headway_df

        except Exception as e:
            logger.error("create_headway_analysis failed: %s", e)
            return _EMPTY
    
    def create_calendar_coverage(
        self,
        calendar_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Create calendar_coverage table.
        
        service_id, monday through sunday flags, start_date, end_date, total_active_days
        """
        coverage = calendar_df.copy()
        
        # Convert dates to string format
        coverage["start_date"] = coverage["start_date"].apply(lambda x: format_gtfs_date(x) if x else None)
        coverage["end_date"] = coverage["end_date"].apply(lambda x: format_gtfs_date(x) if x else None)
        
        coverage["total_active_days"] = _service_days_series(calendar_df)
        
        logger.info(f"Created calendar_coverage: {len(coverage)} service ids")
        return coverage
    
    def create_hourly_departures(self, stop_times_df: pd.DataFrame) -> pd.DataFrame:
        """Departure count by hour of day (0-23) — used for the hourly chart."""
        try:
            parts = stop_times_df["departure_time"].astype(str).str.split(":", n=1, expand=True)
            hours = pd.to_numeric(parts[0], errors="coerce") % 24
            counts = (
                hours.dropna()
                .astype(int)
                .value_counts()
                .reindex(range(24), fill_value=0)
                .sort_index()
                .reset_index()
            )
            counts.columns = ["hour", "departures"]
            logger.info("Created hourly_departures: 24 hour buckets")
            return counts
        except Exception as e:
            logger.error("create_hourly_departures failed: %s", e)
            return pd.DataFrame({"hour": range(24), "departures": 0})

    def create_gold_tables(
        self,
        silver_dfs: Dict[str, pd.DataFrame],
    ) -> Dict[str, pd.DataFrame]:
        """
        Create all Gold layer aggregate tables.
        
        Args:
            silver_dfs: Dictionary of Silver layer DataFrames
            
        Returns:
            Dictionary of Gold layer tables
        """
        gold = {}
        
        # Ensure we have the required DataFrames
        if not all(key in silver_dfs for key in ["routes", "trips", "stop_times", "stops", "calendar", "agency"]):
            logger.warning("Not all required GTFS tables available for Gold layer aggregation")
        
        # Create aggregate tables
        if "routes" in silver_dfs and "trips" in silver_dfs and "stop_times" in silver_dfs and "calendar" in silver_dfs:
            gold["route_summary"] = self.create_route_summary(
                silver_dfs["routes"],
                silver_dfs["trips"],
                silver_dfs["stop_times"],
                silver_dfs["calendar"],
                agency_df=silver_dfs.get("agency"),
            )
        
        if "stops" in silver_dfs and "stop_times" in silver_dfs:
            gold["stop_activity"] = self.create_stop_activity(
                silver_dfs["stops"],
                silver_dfs["stop_times"],
            )
        
        if "agency" in silver_dfs and "routes" in silver_dfs and "trips" in silver_dfs and "calendar" in silver_dfs:
            gold["operator_summary"] = self.create_operator_summary(
                silver_dfs["agency"],
                silver_dfs["routes"],
                silver_dfs["trips"],
                silver_dfs["calendar"],
            )
        
        if "stop_times" in silver_dfs:
            gold["headway_analysis"] = self.create_headway_analysis(
                silver_dfs["stop_times"],
            )
        
        if "calendar" in silver_dfs:
            gold["calendar_coverage"] = self.create_calendar_coverage(
                silver_dfs["calendar"],
            )

        if "stop_times" in silver_dfs:
            gold["hourly_departures"] = self.create_hourly_departures(
                silver_dfs["stop_times"],
            )
        
        self.gold_tables = gold
        
        # Log layer transition
        total_records = sum(len(df) for df in gold.values())
        log_layer_transition(
            logger,
            "Silver",
            "Gold",
            total_records,
            total_records,
        )
        
        return gold
    
    def write_gold_tables(self) -> None:
        """Write Gold layer tables as Parquet and CSV files."""
        for table_name, df in self.gold_tables.items():
            # Write Parquet
            parquet_path = settings.GOLD_OUTPUT / f"{table_name}.parquet"
            write_parquet(df, parquet_path)
            
            # Write CSV for Power BI
            csv_path = settings.GOLD_OUTPUT / f"{table_name}.csv"
            write_csv(df, csv_path)
            
            logger.info(f"Wrote {table_name}: {len(df)} records")


def create_gold_layer(
    silver_dfs: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """
    Execute complete Gold layer creation.
    
    Args:
        silver_dfs: Dictionary of Silver layer DataFrames
        
    Returns:
        Dictionary of Gold layer tables
    """
    gold = GoldLayer()
    gold_tables = gold.create_gold_tables(silver_dfs)
    gold.write_gold_tables()
    
    return gold_tables
