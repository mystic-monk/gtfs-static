"""
Validation rule engine for the Irish GTFS Analytics Platform.

Each rule is a dataclass with fields: rule_code, description, severity, source_file,
and a validate(df) method that accepts a DataFrame and returns a DataFrame of failing records.
All rules are independently testable.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd
from abc import ABC, abstractmethod
from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule(ABC):
    """Base class for all validation rules."""

    rule_code: str
    description: str
    severity: str  # CRITICAL, WARNING, INFO
    source_file: str
    required_files: List[str] = field(default_factory=list)

    @abstractmethod
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate records against this rule.
        
        Args:
            df: Input DataFrame to validate
            
        Returns:
            DataFrame containing only the records that FAIL this rule
        """
        pass


# ============= STOPS.TXT RULES =============

@dataclass
class StopIDNull(ValidationRule):
    """STOP-001: CRITICAL - stop_id is null or empty."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-001",
            description="stop_id is null or empty",
            severity="CRITICAL",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["stop_id"].isna() | (df["stop_id"].astype(str).str.strip() == "")
        return df[mask]


@dataclass
class StopCoordinatesNull(ValidationRule):
    """STOP-002: CRITICAL - stop_lat or stop_lon is null."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-002",
            description="stop_lat or stop_lon is null",
            severity="CRITICAL",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["stop_lat"].isna() | df["stop_lon"].isna()
        return df[mask]


@dataclass
class StopLatOutOfBounds(ValidationRule):
    """STOP-003: CRITICAL - stop_lat outside Ireland bounding box."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-003",
            description=f"stop_lat outside Ireland bounding box ({settings.IRELAND_LAT_MIN} to {settings.IRELAND_LAT_MAX})",
            severity="CRITICAL",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            lat = pd.to_numeric(df["stop_lat"], errors="coerce")
            mask = (lat < settings.IRELAND_LAT_MIN) | (lat > settings.IRELAND_LAT_MAX)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class StopLonOutOfBounds(ValidationRule):
    """STOP-004: CRITICAL - stop_lon outside Ireland bounding box."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-004",
            description=f"stop_lon outside Ireland bounding box ({settings.IRELAND_LON_MIN} to {settings.IRELAND_LON_MAX})",
            severity="CRITICAL",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            lon = pd.to_numeric(df["stop_lon"], errors="coerce")
            mask = (lon < settings.IRELAND_LON_MIN) | (lon > settings.IRELAND_LON_MAX)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class StopNameNull(ValidationRule):
    """STOP-005: WARNING - stop_name is null or empty."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-005",
            description="stop_name is null or empty",
            severity="WARNING",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["stop_name"].isna() | (df["stop_name"].astype(str).str.strip() == "")
        return df[mask]


@dataclass
class StopIDDuplicate(ValidationRule):
    """STOP-006: WARNING - duplicate stop_id within the same operator feed."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-006",
            description="duplicate stop_id within the same operator feed",
            severity="WARNING",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        # Find duplicates
        duplicates = df[df.duplicated(subset=["stop_id"], keep=False)]
        return duplicates


@dataclass
class StopNameEncoding(ValidationRule):
    """STOP-007: INFO - stop_name contains non-ASCII characters or encoding artifacts."""
    
    def __init__(self):
        super().__init__(
            rule_code="STOP-007",
            description="stop_name contains non-ASCII characters or encoding artifacts",
            severity="INFO",
            source_file="stops.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["stop_name"].astype(str).apply(
            lambda x: any(ord(c) > 127 for c in x)
        )
        return df[mask]


# ============= ROUTES.TXT RULES =============

@dataclass
class RouteIDNull(ValidationRule):
    """ROUTE-001: CRITICAL - route_id is null."""
    
    def __init__(self):
        super().__init__(
            rule_code="ROUTE-001",
            description="route_id is null",
            severity="CRITICAL",
            source_file="routes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["route_id"].isna() | (df["route_id"].astype(str).str.strip() == "")
        return df[mask]


@dataclass
class RouteAgencyIDMismatch(ValidationRule):
    """ROUTE-002: CRITICAL - agency_id does not match any record in agency.txt."""

    def __init__(self):
        super().__init__(
            rule_code="ROUTE-002",
            description="agency_id does not match any record in agency.txt",
            severity="CRITICAL",
            source_file="routes.txt",
            required_files=["agency.txt"],
        )
    
    def validate(self, df: pd.DataFrame, agency_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if agency_df is None or len(agency_df) == 0:
            # If no agency data available, check for null agency_ids
            mask = df["agency_id"].isna() | (df["agency_id"].astype(str).str.strip() == "")
            return df[mask]
        
        valid_agencies = set(agency_df["agency_id"].astype(str))
        mask = ~df["agency_id"].astype(str).isin(valid_agencies)
        return df[mask]


@dataclass
class RouteNamesMissing(ValidationRule):
    """ROUTE-003: WARNING - both route_short_name and route_long_name are null."""
    
    def __init__(self):
        super().__init__(
            rule_code="ROUTE-003",
            description="both route_short_name and route_long_name are null",
            severity="WARNING",
            source_file="routes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = (
            (df["route_short_name"].isna() | (df["route_short_name"].astype(str).str.strip() == ""))
            &
            (df["route_long_name"].isna() | (df["route_long_name"].astype(str).str.strip() == ""))
        )
        return df[mask]


@dataclass
class RouteTypeInvalid(ValidationRule):
    """ROUTE-004: WARNING - route_type value is not in GTFS enumeration."""
    
    def __init__(self):
        super().__init__(
            rule_code="ROUTE-004",
            description="route_type value is not in GTFS-defined enumeration (0-7, 11, 12)",
            severity="WARNING",
            source_file="routes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        valid_types = {0, 1, 2, 3, 4, 5, 6, 7, 11, 12}
        try:
            route_types = pd.to_numeric(df["route_type"], errors="coerce")
            mask = ~route_types.isin(valid_types) | route_types.isna()
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class RouteShortNameDuplicate(ValidationRule):
    """ROUTE-005: INFO - duplicate route_short_name within the same agency."""
    
    def __init__(self):
        super().__init__(
            rule_code="ROUTE-005",
            description="duplicate route_short_name within the same agency",
            severity="INFO",
            source_file="routes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        # Duplicates within same agency
        duplicates = df[df.groupby(["agency_id", "route_short_name"]).cumcount() > 0]
        return duplicates


# ============= TRIPS.TXT RULES =============

@dataclass
class TripIDNull(ValidationRule):
    """TRIP-001: CRITICAL - trip_id is null."""
    
    def __init__(self):
        super().__init__(
            rule_code="TRIP-001",
            description="trip_id is null",
            severity="CRITICAL",
            source_file="trips.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["trip_id"].isna() | (df["trip_id"].astype(str).str.strip() == "")
        return df[mask]


@dataclass
class TripRouteIDMissing(ValidationRule):
    """TRIP-002: CRITICAL - route_id does not exist in routes.txt (orphaned trip)."""

    def __init__(self):
        super().__init__(
            rule_code="TRIP-002",
            description="route_id does not exist in routes.txt (orphaned trip)",
            severity="CRITICAL",
            source_file="trips.txt",
            required_files=["routes.txt"],
        )
    
    def validate(self, df: pd.DataFrame, routes_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if routes_df is None or len(routes_df) == 0:
            # No route data available
            return pd.DataFrame()
        
        valid_routes = set(routes_df["route_id"].astype(str))
        mask = ~df["route_id"].astype(str).isin(valid_routes)
        return df[mask]


@dataclass
class TripServiceIDMissing(ValidationRule):
    """TRIP-003: CRITICAL - service_id does not exist in calendar.txt or calendar_dates.txt."""

    def __init__(self):
        super().__init__(
            rule_code="TRIP-003",
            description="service_id does not exist in calendar.txt or calendar_dates.txt",
            severity="CRITICAL",
            source_file="trips.txt",
            required_files=["calendar.txt", "calendar_dates.txt"],
        )
    
    def validate(
        self,
        df: pd.DataFrame,
        calendar_df: Optional[pd.DataFrame] = None,
        calendar_dates_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        valid_services = set()
        
        if calendar_df is not None and len(calendar_df) > 0:
            valid_services.update(calendar_df["service_id"].astype(str))
        
        if calendar_dates_df is not None and len(calendar_dates_df) > 0:
            valid_services.update(calendar_dates_df["service_id"].astype(str))
        
        if not valid_services:
            # No service data available
            return pd.DataFrame()
        
        mask = ~df["service_id"].astype(str).isin(valid_services)
        return df[mask]


@dataclass
class TripShapeIDMissing(ValidationRule):
    """TRIP-004: WARNING - shape_id is populated in trips.txt but does not exist in shapes.txt."""

    def __init__(self):
        super().__init__(
            rule_code="TRIP-004",
            description="shape_id is populated in trips.txt but does not exist in shapes.txt",
            severity="WARNING",
            source_file="trips.txt",
            required_files=["shapes.txt"],
        )
    
    def validate(self, df: pd.DataFrame, shapes_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        # Only check if shape_id is present and not null
        df_with_shapes = df[(~df["shape_id"].isna()) & (df["shape_id"].astype(str).str.strip() != "")]
        
        if shapes_df is None or len(shapes_df) == 0 or len(df_with_shapes) == 0:
            return pd.DataFrame()
        
        valid_shapes = set(shapes_df["shape_id"].astype(str))
        mask = ~df_with_shapes["shape_id"].astype(str).isin(valid_shapes)
        return df_with_shapes[mask]


@dataclass
class TripDirectionIDInvalid(ValidationRule):
    """TRIP-005: INFO - direction_id value is not 0 or 1."""
    
    def __init__(self):
        super().__init__(
            rule_code="TRIP-005",
            description="direction_id value is not 0 or 1",
            severity="INFO",
            source_file="trips.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        # Only validate if direction_id is present
        if "direction_id" not in df.columns:
            return pd.DataFrame()
        
        try:
            direction_id = pd.to_numeric(df["direction_id"], errors="coerce")
            mask = ~direction_id.isin({0, 1}) & direction_id.notna()
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


# ============= STOP_TIMES.TXT RULES =============

@dataclass
class StopTimeTripIDMissing(ValidationRule):
    """ST-001: CRITICAL - trip_id does not exist in trips.txt (orphaned stop time)."""

    def __init__(self):
        super().__init__(
            rule_code="ST-001",
            description="trip_id does not exist in trips.txt (orphaned stop time)",
            severity="CRITICAL",
            source_file="stop_times.txt",
            required_files=["trips.txt"],
        )
    
    def validate(self, df: pd.DataFrame, trips_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if trips_df is None or len(trips_df) == 0:
            return pd.DataFrame()
        
        valid_trips = set(trips_df["trip_id"].astype(str))
        mask = ~df["trip_id"].astype(str).isin(valid_trips)
        return df[mask]


@dataclass
class StopTimeStopIDMissing(ValidationRule):
    """ST-002: CRITICAL - stop_id does not exist in stops.txt (orphaned stop time)."""

    def __init__(self):
        super().__init__(
            rule_code="ST-002",
            description="stop_id does not exist in stops.txt (orphaned stop time)",
            severity="CRITICAL",
            source_file="stop_times.txt",
            required_files=["stops.txt"],
        )
    
    def validate(self, df: pd.DataFrame, stops_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if stops_df is None or len(stops_df) == 0:
            return pd.DataFrame()
        
        valid_stops = set(stops_df["stop_id"].astype(str))
        mask = ~df["stop_id"].astype(str).isin(valid_stops)
        return df[mask]


@dataclass
class StopTimeTimesNull(ValidationRule):
    """ST-003: CRITICAL - arrival_time or departure_time is null."""
    
    def __init__(self):
        super().__init__(
            rule_code="ST-003",
            description="arrival_time or departure_time is null",
            severity="CRITICAL",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["arrival_time"].isna() | df["departure_time"].isna()
        return df[mask]


@dataclass
class StopTimeDepartureBeforeArrival(ValidationRule):
    """ST-004: CRITICAL - departure_time is earlier than arrival_time at the same stop."""
    
    def __init__(self):
        super().__init__(
            rule_code="ST-004",
            description="departure_time is earlier than arrival_time at the same stop sequence",
            severity="CRITICAL",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Convert HH:MM:SS (including >24h GTFS times) to total seconds
            def to_seconds(series):
                parts = series.astype(str).str.split(":", expand=True)
                return (
                    pd.to_numeric(parts[0], errors="coerce") * 3600
                    + pd.to_numeric(parts[1], errors="coerce") * 60
                    + pd.to_numeric(parts[2], errors="coerce")
                )
            mask = to_seconds(df["departure_time"]) < to_seconds(df["arrival_time"])
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class StopTimeExceeds24Hours(ValidationRule):
    """ST-005: WARNING - times exceed 29:59:59 without next-day flag."""
    
    def __init__(self):
        super().__init__(
            rule_code="ST-005",
            description="times exceed 29:59:59 without a next-day service flag (overnight service indicator)",
            severity="WARNING",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Extract hours from time strings
            arrival_hours = df["arrival_time"].astype(str).str.split(":").str[0].astype(int, errors="ignore")
            departure_hours = df["departure_time"].astype(str).str.split(":").str[0].astype(int, errors="ignore")
            
            mask = (arrival_hours > 29) | (departure_hours > 29)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class StopSequenceNotMonotonic(ValidationRule):
    """ST-006: WARNING - stop_sequence values are not monotonically increasing."""
    
    def __init__(self):
        super().__init__(
            rule_code="ST-006",
            description="stop_sequence values are not monotonically increasing within a trip",
            severity="WARNING",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            df2 = df.copy()
            df2["_seq"] = pd.to_numeric(df2["stop_sequence"], errors="coerce")
            df2 = df2.sort_values(["trip_id", "_seq"])
            # Within each trip, flag rows where seq <= previous seq (not strictly increasing)
            prev = df2.groupby("trip_id")["_seq"].shift(1)
            bad_trips = df2.loc[df2["_seq"] <= prev, "trip_id"].unique()
            return df[df["trip_id"].isin(bad_trips)]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class StopTimeZeroDwell(ValidationRule):
    """ST-007: INFO - consecutive scheduled stops share the same departure minute.

    Normal in static GTFS (timing points, short inter-stop gaps). Flagged only
    for informational awareness, not as a data quality issue.
    """

    def __init__(self):
        super().__init__(
            rule_code="ST-007",
            description="consecutive stops share identical scheduled departure_time (normal in static GTFS, informational only)",
            severity="INFO",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            df2 = df.sort_values(["trip_id", "stop_sequence"])
            prev_dep = df2.groupby("trip_id")["departure_time"].shift(1)
            same_trip = df2["trip_id"] == df2["trip_id"].shift(1)
            bad_trips = df2.loc[same_trip & (df2["departure_time"] == prev_dep), "trip_id"].unique()
            return df[df["trip_id"].isin(bad_trips)]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class TripWithSingleStop(ValidationRule):
    """ST-008: INFO - trips with only one stop_time record."""
    
    def __init__(self):
        super().__init__(
            rule_code="ST-008",
            description="trips with only one stop_time record (incomplete trip definition)",
            severity="INFO",
            source_file="stop_times.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            trip_stop_counts = df.groupby("trip_id").size()
            single_stop_trips = trip_stop_counts[trip_stop_counts == 1].index
            mask = df["trip_id"].isin(single_stop_trips)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


# ============= CALENDAR.TXT RULES =============

@dataclass
class CalendarServiceIDNull(ValidationRule):
    """CAL-001: CRITICAL - service_id is null."""
    
    def __init__(self):
        super().__init__(
            rule_code="CAL-001",
            description="service_id is null",
            severity="CRITICAL",
            source_file="calendar.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = df["service_id"].isna() | (df["service_id"].astype(str).str.strip() == "")
        return df[mask]


@dataclass
class CalendarDateRangeInvalid(ValidationRule):
    """CAL-002: CRITICAL - start_date is after end_date."""
    
    def __init__(self):
        super().__init__(
            rule_code="CAL-002",
            description="start_date is after end_date",
            severity="CRITICAL",
            source_file="calendar.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            start_date = pd.to_datetime(df["start_date"], format="%Y%m%d", errors="coerce")
            end_date = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
            mask = start_date > end_date
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class CalendarNoActiveDays(ValidationRule):
    """CAL-003: WARNING - all seven day flags are zero."""
    
    def __init__(self):
        super().__init__(
            rule_code="CAL-003",
            description="all seven day flags are set to zero (no active days defined)",
            severity="WARNING",
            source_file="calendar.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        day_columns = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        
        # Check if all day columns exist
        available_columns = [col for col in day_columns if col in df.columns]
        if not available_columns:
            return pd.DataFrame()
        
        try:
            day_values = df[available_columns].astype(int, errors="ignore")
            mask = (day_values == 0).all(axis=1)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class CalendarDateRangePast(ValidationRule):
    """CAL-004: WARNING - service date range is entirely in the past."""
    
    def __init__(self):
        super().__init__(
            rule_code="CAL-004",
            description="service date range is entirely in the past relative to ingestion date",
            severity="WARNING",
            source_file="calendar.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            from datetime import date
            today = date.today()
            end_date = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
            mask = end_date < pd.Timestamp(today)
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class CalendarDateRangeExceeds366(ValidationRule):
    """CAL-005: INFO - service date range spans more than 366 days."""
    
    def __init__(self):
        super().__init__(
            rule_code="CAL-005",
            description="service date range spans more than 366 days",
            severity="INFO",
            source_file="calendar.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            start_date = pd.to_datetime(df["start_date"], format="%Y%m%d", errors="coerce")
            end_date = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
            days_diff = (end_date - start_date).dt.days
            mask = days_diff > 366
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


# ============= CALENDAR_DATES.TXT RULES =============

@dataclass
class CalendarDatesExceptionTypeInvalid(ValidationRule):
    """CD-001: WARNING - exception_type value is not 1 or 2."""
    
    def __init__(self):
        super().__init__(
            rule_code="CD-001",
            description="exception_type value is not 1 or 2",
            severity="WARNING",
            source_file="calendar_dates.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) == 0:
            return pd.DataFrame()
        
        try:
            exception_type = pd.to_numeric(df["exception_type"], errors="coerce")
            mask = ~exception_type.isin({1, 2}) & exception_type.notna()
            return df[mask]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class CalendarDatesOutOfRange(ValidationRule):
    """CD-002: WARNING - date is outside the range defined in calendar.txt for the same service_id."""

    def __init__(self):
        super().__init__(
            rule_code="CD-002",
            description="date is outside the range defined in calendar.txt for the same service_id",
            severity="WARNING",
            source_file="calendar_dates.txt",
            required_files=["calendar.txt"],
        )
    
    def validate(
        self,
        df: pd.DataFrame,
        calendar_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        if calendar_df is None or len(calendar_df) == 0 or len(df) == 0:
            return pd.DataFrame()

        try:
            # Vectorized: merge calendar bounds into calendar_dates, then compare
            bounds = calendar_df[["service_id", "start_date", "end_date"]].copy()
            bounds["_start"] = pd.to_datetime(bounds["start_date"], format="%Y%m%d", errors="coerce")
            bounds["_end"] = pd.to_datetime(bounds["end_date"], format="%Y%m%d", errors="coerce")

            merged = df.merge(bounds[["service_id", "_start", "_end"]], on="service_id", how="left")
            cd_dates = pd.to_datetime(merged["date"], format="%Y%m%d", errors="coerce")
            out_of_range = merged["_start"].notna() & ((cd_dates < merged["_start"]) | (cd_dates > merged["_end"]))
            return df[out_of_range.values]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


# ============= SHAPES.TXT RULES =============

@dataclass
class ShapeIDUnused(ValidationRule):
    """SHP-001: WARNING - shape_id exists in shapes.txt but is not referenced by any trip."""

    def __init__(self):
        super().__init__(
            rule_code="SHP-001",
            description="shape_id exists in shapes.txt but is not referenced by any trip",
            severity="WARNING",
            source_file="shapes.txt",
            required_files=["trips.txt"],
        )
    
    def validate(self, df: pd.DataFrame, trips_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if trips_df is None or len(trips_df) == 0 or len(df) == 0:
            return pd.DataFrame()
        
        referenced_shapes = set(
            trips_df[trips_df["shape_id"].notna()]["shape_id"].astype(str)
        )
        mask = ~df["shape_id"].astype(str).isin(referenced_shapes)
        return df[mask]


@dataclass
class ShapeSequenceNotMonotonic(ValidationRule):
    """SHP-002: WARNING - shape_pt_sequence is not monotonically increasing."""
    
    def __init__(self):
        super().__init__(
            rule_code="SHP-002",
            description="shape_pt_sequence is not monotonically increasing within a shape_id",
            severity="WARNING",
            source_file="shapes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            df2 = df.copy()
            df2["_seq"] = pd.to_numeric(df2["shape_pt_sequence"], errors="coerce")
            df2 = df2.sort_values(["shape_id", "_seq"])
            prev = df2.groupby("shape_id")["_seq"].shift(1)
            bad_shapes = df2.loc[df2["_seq"] <= prev, "shape_id"].unique()
            return df[df["shape_id"].isin(bad_shapes)]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


@dataclass
class ShapePointsIdentical(ValidationRule):
    """SHP-003: WARNING - consecutive shape points with identical lat/lon coordinates."""
    
    def __init__(self):
        super().__init__(
            rule_code="SHP-003",
            description="consecutive shape points with identical lat/lon coordinates",
            severity="WARNING",
            source_file="shapes.txt",
        )
    
    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            df2 = df.sort_values(["shape_id", "shape_pt_sequence"])
            same_shape = df2["shape_id"] == df2["shape_id"].shift(1)
            same_lat = df2["shape_pt_lat"] == df2["shape_pt_lat"].shift(1)
            same_lon = df2["shape_pt_lon"] == df2["shape_pt_lon"].shift(1)
            bad_shapes = df2.loc[same_shape & same_lat & same_lon, "shape_id"].unique()
            return df[df["shape_id"].isin(bad_shapes)]
        except Exception as e:
            logger.error("Rule %s failed: %s", self.rule_code, e)
            return pd.DataFrame()


# ============= CROSS-FILE REFERENTIAL INTEGRITY RULES =============

@dataclass
class AgencyIDMismatchInRoutes(ValidationRule):
    """REF-001: CRITICAL - agency_id in routes.txt not present in agency.txt."""

    def __init__(self):
        super().__init__(
            rule_code="REF-001",
            description="agency_id in routes.txt not present in agency.txt",
            severity="CRITICAL",
            source_file="routes.txt",
            required_files=["agency.txt"],
        )
    
    def validate(self, df: pd.DataFrame, agency_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if agency_df is None or len(agency_df) == 0:
            return pd.DataFrame()
        
        valid_agencies = set(agency_df["agency_id"].astype(str))
        mask = ~df["agency_id"].astype(str).isin(valid_agencies)
        return df[mask]


@dataclass
class TripsNotInStopTimes(ValidationRule):
    """REF-002: CRITICAL - trips present in stop_times.txt with no corresponding record in trips.txt."""

    def __init__(self):
        super().__init__(
            rule_code="REF-002",
            description="trips present in stop_times.txt with no corresponding record in trips.txt",
            severity="CRITICAL",
            source_file="stop_times.txt",
            required_files=["trips.txt"],
        )
    
    def validate(self, df: pd.DataFrame, trips_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if trips_df is None or len(trips_df) == 0:
            return pd.DataFrame()
        
        valid_trips = set(trips_df["trip_id"].astype(str))
        mask = ~df["trip_id"].astype(str).isin(valid_trips)
        return df[mask]


@dataclass
class RoutesWithoutTrips(ValidationRule):
    """REF-003: WARNING - routes with no trips defined."""

    def __init__(self):
        super().__init__(
            rule_code="REF-003",
            description="routes with no trips defined",
            severity="WARNING",
            source_file="routes.txt",
            required_files=["trips.txt"],
        )
    
    def validate(self, df: pd.DataFrame, trips_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if trips_df is None or len(trips_df) == 0:
            return df  # All routes have no trips
        
        used_routes = set(trips_df["route_id"].astype(str))
        mask = ~df["route_id"].astype(str).isin(used_routes)
        return df[mask]


@dataclass
class StopsWithoutStopTimes(ValidationRule):
    """REF-004: WARNING - stops with no stop_times referencing them (phantom stops)."""

    def __init__(self):
        super().__init__(
            rule_code="REF-004",
            description="stops with no stop_times referencing them (phantom stops)",
            severity="WARNING",
            source_file="stops.txt",
            required_files=["stop_times.txt"],
        )
    
    def validate(self, df: pd.DataFrame, stop_times_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if stop_times_df is None or len(stop_times_df) == 0:
            return df  # All stops have no stop times
        
        used_stops = set(stop_times_df["stop_id"].astype(str))
        mask = ~df["stop_id"].astype(str).isin(used_stops)
        return df[mask]


@dataclass
class AgenciesWithoutRoutes(ValidationRule):
    """REF-005: INFO - agencies defined in agency.txt with no routes assigned."""

    def __init__(self):
        super().__init__(
            rule_code="REF-005",
            description="agencies defined in agency.txt with no routes assigned",
            severity="INFO",
            source_file="agency.txt",
            required_files=["routes.txt"],
        )
    
    def validate(self, df: pd.DataFrame, routes_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if routes_df is None or len(routes_df) == 0:
            return df  # All agencies have no routes
        
        used_agencies = set(routes_df["agency_id"].astype(str))
        mask = ~df["agency_id"].astype(str).isin(used_agencies)
        return df[mask]


# Rule Registry
ALL_RULES = [
    # Stops
    StopIDNull(),
    StopCoordinatesNull(),
    StopLatOutOfBounds(),
    StopLonOutOfBounds(),
    StopNameNull(),
    StopIDDuplicate(),
    StopNameEncoding(),
    # Routes
    RouteIDNull(),
    RouteAgencyIDMismatch(),
    RouteNamesMissing(),
    RouteTypeInvalid(),
    RouteShortNameDuplicate(),
    # Trips
    TripIDNull(),
    TripRouteIDMissing(),
    TripServiceIDMissing(),
    TripShapeIDMissing(),
    TripDirectionIDInvalid(),
    # Stop times
    StopTimeTripIDMissing(),
    StopTimeStopIDMissing(),
    StopTimeTimesNull(),
    StopTimeDepartureBeforeArrival(),
    StopTimeExceeds24Hours(),
    StopSequenceNotMonotonic(),
    StopTimeZeroDwell(),
    TripWithSingleStop(),
    # Calendar
    CalendarServiceIDNull(),
    CalendarDateRangeInvalid(),
    CalendarNoActiveDays(),
    CalendarDateRangePast(),
    CalendarDateRangeExceeds366(),
    # Calendar dates
    CalendarDatesExceptionTypeInvalid(),
    CalendarDatesOutOfRange(),
    # Shapes
    ShapeIDUnused(),
    ShapeSequenceNotMonotonic(),
    ShapePointsIdentical(),
    # Cross-file
    AgencyIDMismatchInRoutes(),
    TripsNotInStopTimes(),
    RoutesWithoutTrips(),
    StopsWithoutStopTimes(),
    AgenciesWithoutRoutes(),
]


def get_rules_by_severity(severity: str = None):
    """Get rules filtered by severity."""
    if severity is None:
        return ALL_RULES
    return [rule for rule in ALL_RULES if rule.severity == severity]


def get_rules_by_source(source_file: str):
    """Get rules filtered by source file."""
    return [rule for rule in ALL_RULES if rule.source_file == source_file]
