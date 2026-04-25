"""Tests for the ValidationRunner orchestrator."""
import pandas as pd
import pytest

from src.validation.runner import ValidationRunner


@pytest.fixture
def gtfs_dfs(stops_df, routes_df, agency_df, trips_df, stop_times_df, calendar_df):
    return {
        "stops": stops_df,
        "routes": routes_df,
        "agency": agency_df,
        "trips": trips_df,
        "stop_times": stop_times_df,
        "calendar": calendar_df,
    }


class TestValidationRunnerBasic:
    def test_returns_tuple_of_two(self, gtfs_dfs):
        runner = ValidationRunner()
        result = runner.validate_gtfs_data(gtfs_dfs)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_validated_dfs_keys_match_input(self, gtfs_dfs):
        runner = ValidationRunner()
        validated, _ = runner.validate_gtfs_data(gtfs_dfs)
        assert set(validated.keys()) == set(gtfs_dfs.keys())

    def test_clean_data_produces_empty_quarantine(self, gtfs_dfs):
        runner = ValidationRunner()
        _, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        assert len(quarantine) == 0

    def test_null_stop_id_goes_to_quarantine(self, gtfs_dfs):
        gtfs_dfs["stops"] = pd.DataFrame({
            "stop_id": [None, "S2"],
            "stop_name": ["A", "B"],
            "stop_lat": [53.3, 53.4],
            "stop_lon": [-6.2, -6.3],
        })
        runner = ValidationRunner()
        _, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        assert len(quarantine) > 0
        assert "STOP-001" in quarantine["rule_code"].values

    def test_warning_violations_not_quarantined(self, gtfs_dfs):
        # STOP-005 is WARNING (missing stop name) — should not quarantine
        gtfs_dfs["stops"] = pd.DataFrame({
            "stop_id": ["S1"],
            "stop_name": [None],
            "stop_lat": [53.3],
            "stop_lon": [-6.2],
        })
        runner = ValidationRunner()
        _, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        # Quarantine should not contain STOP-005 (WARNING)
        if len(quarantine) > 0:
            assert "STOP-005" not in quarantine["rule_code"].values

    def test_missing_file_skipped_gracefully(self, gtfs_dfs):
        # Remove a file that is present; runner should skip its rules without raising
        del gtfs_dfs["stop_times"]
        runner = ValidationRunner()
        validated, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        assert isinstance(quarantine, pd.DataFrame)


class TestValidationRunnerCrossFile:
    def test_orphaned_trip_quarantined(self, gtfs_dfs):
        gtfs_dfs["stop_times"] = pd.DataFrame({
            "trip_id": ["T_ORPHAN"],
            "stop_id": ["S1"],
            "arrival_time": ["08:00:00"],
            "departure_time": ["08:00:00"],
            "stop_sequence": [1],
        })
        runner = ValidationRunner()
        _, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        quarantine_codes = quarantine["rule_code"].values if len(quarantine) > 0 else []
        assert "ST-001" in quarantine_codes or "REF-002" in quarantine_codes

    def test_agency_mismatch_quarantined(self, gtfs_dfs):
        gtfs_dfs["routes"] = pd.DataFrame({
            "route_id": ["R1"],
            "agency_id": ["AG_UNKNOWN"],
            "route_short_name": ["1"],
            "route_long_name": ["Route One"],
            "route_type": [3],
        })
        runner = ValidationRunner()
        _, quarantine = runner.validate_gtfs_data(gtfs_dfs)
        quarantine_codes = quarantine["rule_code"].values if len(quarantine) > 0 else []
        assert "ROUTE-002" in quarantine_codes or "REF-001" in quarantine_codes


class TestValidationRunnerSummary:
    def test_summary_populated_on_violations(self, gtfs_dfs):
        gtfs_dfs["stops"] = pd.DataFrame({
            "stop_id": [None],
            "stop_name": [None],
            "stop_lat": [53.3],
            "stop_lon": [-6.2],
        })
        runner = ValidationRunner()
        runner.validate_gtfs_data(gtfs_dfs)
        report = runner.get_validation_report()
        assert not report.empty
        assert "rule_code" in report.columns
        assert "violation_count" in report.columns

    def test_operator_name_recorded_in_summary(self, gtfs_dfs):
        gtfs_dfs["stops"] = pd.DataFrame({
            "stop_id": [None],
            "stop_name": ["X"],
            "stop_lat": [53.3],
            "stop_lon": [-6.2],
        })
        runner = ValidationRunner()
        runner.validate_gtfs_data(gtfs_dfs, operator_name="Dublin Bus")
        report = runner.get_validation_report()
        assert (report["operator"] == "Dublin Bus").any()
