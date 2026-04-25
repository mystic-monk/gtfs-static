"""
Date and time utilities for the Irish GTFS Analytics Platform.
"""
from datetime import datetime, date, timedelta
from typing import Optional
import pandas as pd


def parse_gtfs_date(date_str: str) -> Optional[date]:
    """
    Parse a GTFS date string (YYYYMMDD format) to a Python date object.
    
    Args:
        date_str: Date string in YYYYMMDD format
        
    Returns:
        Python date object or None if invalid
    """
    if not date_str or pd.isna(date_str):
        return None
    
    try:
        date_str = str(date_str).strip()
        if len(date_str) != 8 or not date_str.isdigit():
            return None
        return datetime.strptime(date_str, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def parse_gtfs_time(time_str: str) -> Optional[str]:
    """
    Parse a GTFS time string (HH:MM:SS format, can exceed 24 hours).
    
    Args:
        time_str: Time string in HH:MM:SS format
        
    Returns:
        Normalized time string or None if invalid
    """
    if not time_str or pd.isna(time_str):
        return None
    
    try:
        time_str = str(time_str).strip()
        parts = time_str.split(":")
        if len(parts) != 3:
            return None
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        
        # Validate ranges (allowing hours > 24 for overnight services)
        if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59:
            return None
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError, AttributeError):
        return None


def time_exceeds_24h(time_str: str) -> bool:
    """
    Check if a GTFS time string exceeds 24 hours (overnight service).
    
    Args:
        time_str: Time string in HH:MM:SS format
        
    Returns:
        True if hours >= 24, False otherwise
    """
    if not time_str:
        return False
    
    try:
        hours = int(str(time_str).split(":")[0])
        return hours >= 24
    except (ValueError, IndexError):
        return False


def convert_time_to_24h(time_str: str) -> tuple[str, bool]:
    """
    Convert a GTFS time exceeding 24 hours to 24-hour format with next-day flag.
    
    Args:
        time_str: Time string in HH:MM:SS format
        
    Returns:
        Tuple of (normalized_time_str, is_next_day)
    """
    if not time_str:
        return None, False
    
    try:
        parts = str(time_str).split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        
        is_next_day = hours >= 24
        if is_next_day:
            hours = hours % 24
        
        normalized = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return normalized, is_next_day
    except (ValueError, IndexError):
        return time_str, False


def get_active_service_dates(
    start_date: date,
    end_date: date,
    day_flags: dict,  # {monday: 0/1, tuesday: 0/1, ..., sunday: 0/1}
) -> int:
    """
    Calculate number of active service days in a date range.

    Uses O(7) arithmetic instead of iterating day-by-day — safe on year-long ranges.
    """
    if not start_date or not end_date:
        return 0

    # Accept both date objects and YYYYMMDD strings
    if isinstance(start_date, str):
        try:
            start_date = datetime.strptime(start_date, "%Y%m%d").date()
        except ValueError:
            return 0
    if isinstance(end_date, str):
        try:
            end_date = datetime.strptime(end_date, "%Y%m%d").date()
        except ValueError:
            return 0

    delta = (end_date - start_date).days
    if delta < 0:
        return 0

    # weekday() → 0=Monday … 6=Sunday, matching GTFS day_flags key order
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    start_dow = start_date.weekday()

    active = 0
    for i, day_name in enumerate(day_names):
        if not day_flags.get(day_name, 0):
            continue
        # First occurrence of this weekday on or after start_date
        offset = (i - start_dow) % 7
        if offset > delta:
            continue
        active += (delta - offset) // 7 + 1

    return active


def days_until_service(
    start_date: date,
    reference_date: Optional[date] = None,
) -> int:
    """
    Calculate days from reference date (or today) until a service start date.
    
    Args:
        start_date: Service start date
        reference_date: Reference date (defaults to today)
        
    Returns:
        Number of days until service (negative if in the past)
    """
    if reference_date is None:
        reference_date = date.today()
    
    if not start_date:
        return float("inf")
    
    delta = (start_date - reference_date).days
    return delta


def is_feed_stale(
    end_date: date,
    staleness_threshold_days: int = 7,
    reference_date: Optional[date] = None,
) -> bool:
    """
    Check if a feed is stale (no active services in the next N days).
    
    Args:
        end_date: Feed end date
        staleness_threshold_days: Number of days to check ahead
        reference_date: Reference date (defaults to today)
        
    Returns:
        True if feed is stale, False otherwise
    """
    if reference_date is None:
        reference_date = date.today()
    
    if not end_date:
        return True
    
    future_date = reference_date + timedelta(days=staleness_threshold_days)
    return end_date < future_date


def week_of_year(dt: date) -> int:
    """
    Get ISO week number from a date.
    
    Args:
        dt: Date object
        
    Returns:
        ISO week number (1-53)
    """
    if not dt:
        return None
    
    return dt.isocalendar()[1]


def format_gtfs_date(dt: date) -> str:
    """
    Format a date object to GTFS format (YYYYMMDD).
    
    Args:
        dt: Date object
        
    Returns:
        Date string in YYYYMMDD format
    """
    if not dt:
        return None
    
    return dt.strftime("%Y%m%d")
