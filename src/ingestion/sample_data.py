"""
Generate sample GTFS data for testing the platform without real feeds.

Creates mock GTFS CSV files (stops.txt, routes.txt, trips.txt, stop_times.txt, etc.)
that mimic Dublin Bus network structure.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import zipfile
import io

# Sample stops data (Dublin area)
SAMPLE_STOPS = [
    # Core City Centre
    ("8220DB000001", "O'Connell Street", 53.3498, -6.2603, "Dublin"),
    ("8220DB000002", "Parnell Square", 53.3533, -6.2638, "Dublin"),
    ("8220DB000003", "Dorset Street", 53.3582, -6.2636, "Dublin"),
    ("8220DB000004", "Drumcondra Road", 53.3665, -6.2570, "Dublin"),
    ("8220DB000005", "Glasnevin", 53.3716, -6.2697, "Dublin"),
    ("8220DB000006", "Finglas Road", 53.3823, -6.2902, "Dublin"),
    ("8220DB000007", "Blanchardstown Centre", 53.3883, -6.3765, "Dublin"),
    ("8220DB000008", "Dublin Airport", 53.4264, -6.2499, "Dublin"),
    ("8220DB000009", "Santry", 53.3930, -6.2426, "Dublin"),
    ("8220DB000010", "Whitehall", 53.3773, -6.2466, "Dublin"),
    ("8220DB000011", "Grafton Street", 53.3414, -6.2590, "Dublin"),
    ("8220DB000012", "Ranelagh", 53.3265, -6.2615, "Dublin"),
    ("8220DB000013", "Dundrum", 53.2930, -6.2448, "Dublin"),
    ("8220DB000014", "Ballinteer", 53.2837, -6.2575, "Dublin"),
    ("8220DB000015", "Phoenix Park Gate", 53.3558, -6.3138, "Dublin"),
    ("8220DB000016", "Heuston Station", 53.3464, -6.2922, "Dublin"),
    ("8220DB000017", "Thomas Street", 53.3431, -6.2836, "Dublin"),
    ("8220DB000018", "Dame Street", 53.3439, -6.2656, "Dublin"),
    ("8220DB000019", "Pearse Street", 53.3435, -6.2508, "Dublin"),
    ("8220DB000020", "Booterstown", 53.3159, -6.1985, "Dublin"),
    ("8220DB000021", "Blackrock", 53.3016, -6.1782, "Dublin"),
    ("8220DB000022", "Dún Laoghaire", 53.2936, -6.1347, "Dublin"),
    ("8220DB000023", "Ringsend Road", 53.3390, -6.2308, "Dublin"),
    ("8220DB000024", "Grand Canal Dock", 53.3396, -6.2380, "Dublin"),
    ("8220DB000025", "Rathmines", 53.3243, -6.2632, "Dublin"),
    ("8220DB000026", "Terenure", 53.3105, -6.2791, "Dublin"),
    ("8220DB000027", "Templeogue", 53.2977, -6.3037, "Dublin"),
    ("8220DB000028", "Tallaght", 53.2867, -6.3562, "Dublin"),
    ("8220DB000029", "Donnybrook", 53.3189, -6.2383, "Dublin"),
    ("8220DB000030", "Stillorgan", 53.2904, -6.2101, "Dublin"),
]

# Sample routes
SAMPLE_ROUTES = [
    ("39A", "dublin_bus", "39A", "UCD to Ongar", 3, None, "1a8b2b"),
    ("16", "dublin_bus", "16", "Airport to Ballinteer", 3, None, "2b3c4d"),
    ("46A", "dublin_bus", "46A", "Phoenix Park to Dún Laoghaire", 3, None, "3c4d5e"),
    ("77A", "dublin_bus", "77A", "Ringsend to Tallaght", 3, None, "4d5e6f"),
    ("145", "dublin_bus", "145", "Heuston to Bray", 3, None, "5e6f7g"),
]

# Service dates (today's date for sample)
SERVICE_CALENDAR = {
    "service_id": "weekday_service",
    "monday": 1,
    "tuesday": 1,
    "wednesday": 1,
    "thursday": 1,
    "friday": 1,
    "saturday": 0,
    "sunday": 0,
    "start_date": 20260101,
    "end_date": 20261231,
}

PEAK_HEADWAY = 8  # minutes
OFFPEAK_HEADWAY = 15  # minutes


def generate_stops_df():
    """Generate stops.txt DataFrame."""
    data = []
    for stop_id, stop_name, stop_lat, stop_lon, city in SAMPLE_STOPS:
        data.append({
            "stop_id": stop_id,
            "stop_code": stop_id,
            "stop_name": stop_name,
            "stop_desc": f"Stop in {city}",
            "stop_lat": stop_lat,
            "stop_lon": stop_lon,
            "zone_id": "",
            "stop_url": "",
            "location_type": 0,
            "parent_station": "",
        })
    return pd.DataFrame(data)


def generate_routes_df():
    """Generate routes.txt DataFrame."""
    data = []
    for route_id, agency_id, route_short_name, route_long_name, route_type, route_url, route_color in SAMPLE_ROUTES:
        data.append({
            "route_id": route_id,
            "agency_id": agency_id,
            "route_short_name": route_short_name,
            "route_long_name": route_long_name,
            "route_desc": "",
            "route_type": route_type,
            "route_url": route_url if route_url else "",
            "route_color": route_color,
            "route_text_color": "FFFFFF",
        })
    return pd.DataFrame(data)


def generate_calendar_df():
    """Generate calendar.txt DataFrame."""
    return pd.DataFrame([SERVICE_CALENDAR])


def generate_calendar_dates_df():
    """Generate calendar_dates.txt DataFrame (empty for simplicity)."""
    return pd.DataFrame(columns=[
        "service_id", "date", "exception_type"
    ])


def generate_agency_df():
    """Generate agency.txt DataFrame."""
    return pd.DataFrame([{
        "agency_id": "dublin_bus",
        "agency_name": "Dublin Bus",
        "agency_url": "https://www.dublinbus.ie",
        "agency_timezone": "Europe/Dublin",
        "agency_lang": "en",
        "agency_phone": "+353 1 873 4222",
    }])


def generate_trips_and_stop_times():
    """Generate trips.txt and stop_times.txt DataFrames."""
    trips_data = []
    stop_times_data = []
    
    trip_id_counter = 0
    
    # Map stops to routes
    route_stops = {
        "39A": ["8220DB000001", "8220DB000002", "8220DB000003", "8220DB000004", "8220DB000005"],
        "16": ["8220DB000008", "8220DB000009", "8220DB000010", "8220DB000011", "8220DB000012", "8220DB000013", "8220DB000014"],
        "46A": ["8220DB000015", "8220DB000016", "8220DB000017", "8220DB000018", "8220DB000019", "8220DB000020", "8220DB000021", "8220DB000022"],
        "77A": ["8220DB000023", "8220DB000024", "8220DB000025", "8220DB000026", "8220DB000027", "8220DB000028"],
        "145": ["8220DB000016", "8220DB000019", "8220DB000029", "8220DB000030"],
    }
    
    # Create trips for each route
    for route_id in ["39A", "16", "46A", "77A", "145"]:
        stop_ids = route_stops[route_id]
        
        # Create departures throughout the day
        departure_minutes = []
        
        # Morning peak: 07:00 – 09:30 every 8 min
        t = 7 * 60
        while t < 9 * 60 + 30:
            departure_minutes.append(t)
            t += PEAK_HEADWAY
        
        # Midday: 09:30 – 16:00 every 15 min
        t = 9 * 60 + 30
        while t < 16 * 60:
            departure_minutes.append(t)
            t += OFFPEAK_HEADWAY
        
        # Evening peak: 16:00 – 19:00 every 8 min
        t = 16 * 60
        while t < 19 * 60:
            departure_minutes.append(t)
            t += PEAK_HEADWAY
        
        # Evening: 19:00 – 23:00 every 25 min
        t = 19 * 60
        while t < 23 * 60:
            departure_minutes.append(t)
            t += 25
        
        # Create trip for each departure
        for dep_min in departure_minutes:
            trip_id = f"trip_{trip_id_counter:05d}"
            trip_id_counter += 1
            
            trips_data.append({
                "route_id": route_id,
                "service_id": "weekday_service",
                "trip_id": trip_id,
                "trip_headsign": stop_ids[-1],
                "direction_id": 0,
                "block_id": "",
                "shape_id": "",
                "wheelchair_accessible": 1,
                "bikes_allowed": 0,
            })
            
            # Create stop times for each stop in the route
            for seq, stop_id in enumerate(stop_ids, 1):
                arr_min = dep_min + (seq - 1) * 3
                dep_min_actual = arr_min
                
                if seq < len(stop_ids):  # Not the last stop
                    dep_min_actual = arr_min + 1
                
                arrival_time = f"{arr_min // 60:02d}:{arr_min % 60:02d}:00"
                departure_time = f"{dep_min_actual // 60:02d}:{dep_min_actual % 60:02d}:00"
                
                stop_times_data.append({
                    "trip_id": trip_id,
                    "arrival_time": arrival_time,
                    "departure_time": departure_time,
                    "stop_id": stop_id,
                    "stop_sequence": seq,
                    "stop_headsign": "",
                    "pickup_type": 0,
                    "drop_off_type": 0,
                })
    
    return pd.DataFrame(trips_data), pd.DataFrame(stop_times_data)


def create_sample_gtfs_zip(output_path):
    """Create a sample GTFS ZIP file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate all dataframes
    stops_df = generate_stops_df()
    routes_df = generate_routes_df()
    calendar_df = generate_calendar_df()
    calendar_dates_df = generate_calendar_dates_df()
    agency_df = generate_agency_df()
    trips_df, stop_times_df = generate_trips_and_stop_times()
    
    # Create ZIP file with GTFS files
    with zipfile.ZipFile(output_path, 'w') as zf:
        # Write each CSV file to the ZIP
        zf.writestr('agency.txt', agency_df.to_csv(index=False))
        zf.writestr('stops.txt', stops_df.to_csv(index=False))
        zf.writestr('routes.txt', routes_df.to_csv(index=False))
        zf.writestr('calendar.txt', calendar_df.to_csv(index=False))
        zf.writestr('calendar_dates.txt', calendar_dates_df.to_csv(index=False))
        zf.writestr('trips.txt', trips_df.to_csv(index=False))
        zf.writestr('stop_times.txt', stop_times_df.to_csv(index=False))
    
    print(f"✅ Created sample GTFS ZIP: {output_path}")
    return output_path


if __name__ == "__main__":
    # Create sample data
    sample_zip = Path("outputs/sample_gtfs.zip")
    create_sample_gtfs_zip(sample_zip)