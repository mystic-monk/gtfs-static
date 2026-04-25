"""Shared pytest fixtures for GTFS test suite."""
import pandas as pd
import pytest


@pytest.fixture
def stops_df():
    return pd.DataFrame({
        "stop_id": ["S1", "S2", "S3"],
        "stop_name": ["Stop One", "Stop Two", "Stop Three"],
        "stop_lat": [53.3, 53.4, 53.5],
        "stop_lon": [-6.2, -6.3, -6.4],
    })


@pytest.fixture
def routes_df():
    return pd.DataFrame({
        "route_id": ["R1", "R2"],
        "agency_id": ["AG1", "AG1"],
        "route_short_name": ["1", "2"],
        "route_long_name": ["Route One", "Route Two"],
        "route_type": [3, 3],
    })


@pytest.fixture
def agency_df():
    return pd.DataFrame({
        "agency_id": ["AG1"],
        "agency_name": ["Dublin Bus"],
    })


@pytest.fixture
def trips_df():
    return pd.DataFrame({
        "trip_id": ["T1", "T2"],
        "route_id": ["R1", "R1"],
        "service_id": ["SVC1", "SVC1"],
        "shape_id": [None, None],
        "direction_id": [0, 1],
    })


@pytest.fixture
def stop_times_df():
    return pd.DataFrame({
        "trip_id": ["T1", "T1", "T1"],
        "stop_id": ["S1", "S2", "S3"],
        "arrival_time": ["08:00:00", "08:10:00", "08:20:00"],
        "departure_time": ["08:00:00", "08:10:00", "08:20:00"],
        "stop_sequence": [1, 2, 3],
    })


@pytest.fixture
def calendar_df():
    return pd.DataFrame({
        "service_id": ["SVC1"],
        "monday": [1],
        "tuesday": [1],
        "wednesday": [1],
        "thursday": [1],
        "friday": [1],
        "saturday": [0],
        "sunday": [0],
        "start_date": ["20260101"],
        "end_date": ["20261231"],
    })
