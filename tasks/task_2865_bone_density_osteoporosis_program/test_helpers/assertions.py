"""Domain assertions for the Bone Density & Osteoporosis Program API."""

import re
from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_APPEND_ONLY_FORBIDDEN = ("updated_at", "version")
_FRACTION = re.compile(r"\.(\d+)Z$")


# ── Envelope-level shape ────────────────────────────────────────────────────


def assert_identity_fields(resource: Dict[str, Any]) -> None:
    """Every resource carries a server-minted UUID and a creation stamp."""
    assert is_valid_uuid(resource.get("id", "")), (
        f"id must be a UUID with no type prefix: {resource.get('id')!r}"
    )
    assert is_iso8601_timestamp(resource.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp: {resource.get('created_at')!r}"
    )


def assert_versioned_resource(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A mutable resource carries updated_at and an integer version."""
    assert_identity_fields(resource)
    assert is_iso8601_timestamp(resource.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp: {resource.get('updated_at')!r}"
    )
    assert isinstance(resource.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"Expected version {expected_version}, got {resource.get('version')}"
        )


def assert_append_only_resource(resource: Dict[str, Any]) -> None:
    """An append-only record exposes only id and created_at, never the mutation pair."""
    assert_identity_fields(resource)
    for field in _APPEND_ONLY_FORBIDDEN:
        assert field not in resource, (
            f"{field} must be absent from an append-only record, not null or zero; "
            f"got {resource.get(field)!r}"
        )


def assert_echoes(resource: Dict[str, Any], payload: Dict[str, Any]) -> None:
    """Every field supplied on creation is echoed back unchanged."""
    for key, value in payload.items():
        assert key in resource, f"Response is missing the submitted field {key!r}"
        if isinstance(value, float):
            assert resource[key] == pytest.approx(value, abs=0.0001), (
                f"{key}: expected {value}, got {resource[key]}"
            )
        else:
            assert resource[key] == value, (
                f"{key}: expected {value!r}, got {resource[key]!r}"
            )


def assert_field_absent_or_none(resource: Dict[str, Any], field: str) -> None:
    assert resource.get(field) is None, (
        f"{field} should not have been accepted from the client: {resource.get(field)!r}"
    )


# ── Time and numeric precision ──────────────────────────────────────────────


def normalise_instant(value: str) -> str:
    """Strip a trailing all-zero fractional part so two instants can be compared."""
    if not isinstance(value, str):
        return value
    match = _FRACTION.search(value)
    if match and set(match.group(1)) == {"0"}:
        return value[: match.start()] + "Z"
    return value


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Two ISO-8601 instants denote the same moment, whatever their sub-second width."""
    assert isinstance(actual, str), f"{field}: expected an instant string, got {actual!r}"
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"{field}: expected instant {expected}, got {actual}"
    )


def assert_decimal_places(value: Any, places: int, field: str = "value") -> None:
    """A numeric quantity carries no more than the specified number of decimals."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), places) == pytest.approx(float(value)), (
        f"{field} carries more than {places} decimal places: {value}"
    )


def assert_score_one_decimal(value: Any, expected: float, field: str = "score") -> None:
    """A T-score or Z-score equals the expected one-decimal figure."""
    assert value == pytest.approx(expected, abs=0.01), (
        f"{field}: expected {expected}, got {value}"
    )
    assert_decimal_places(value, 1, field)


def assert_four_decimals(value: Any, expected: float, field: str = "value") -> None:
    assert value == pytest.approx(expected, abs=0.00005), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_three_decimals(value: Any, expected: float, field: str = "value") -> None:
    assert value == pytest.approx(expected, abs=0.0005), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_two_decimals(value: Any, expected: float, field: str = "value") -> None:
    assert value == pytest.approx(expected, abs=0.005), (
        f"{field}: expected {expected}, got {value}"
    )


# ── Entity assertions ───────────────────────────────────────────────────────


def assert_fresh_densitometer(device: Dict[str, Any]) -> None:
    """A newly registered device is active, ungenerated and uncertified."""
    assert device["status"] == "ACTIVE"
    assert device["calibration_generation"] == 1
    assert device["cross_cal_factor"] == pytest.approx(1.0)
    assert device["consecutive_qc_pass_count"] == 0
    for field in (
        "rms_sd_g_cm2",
        "precision_degrees_of_freedom",
        "lsc_g_cm2",
        "precision_technologist_user_id",
        "precision_certified_at",
        "last_qc_result",
        "last_qc_run_at",
        "qc_hold_started_at",
        "qc_hold_reason_code",
    ):
        assert device[field] is None, f"{field} must start null, got {device[field]!r}"


def assert_fresh_patient(patient: Dict[str, Any]) -> None:
    """A freshly registered patient has zeroed counters and no screening history."""
    assert patient["open_scheduled_order_count"] == 0
    assert patient["lifetime_screening_scan_count"] == 0
    for field in (
        "baseline_report_id",
        "last_finalized_report_id",
        "current_screening_interval_months",
        "next_eligible_scan_date",
    ):
        assert patient[field] is None, f"{field} must start null, got {patient[field]!r}"


def assert_qc_scoring(
    run: Dict[str, Any],
    expected_deviation: float,
    expected_sd_units: float,
    expected_result: str,
) -> None:
    assert_four_decimals(run["deviation_g_cm2"], expected_deviation, "deviation_g_cm2")
    assert_three_decimals(run["deviation_sd_units"], expected_sd_units, "deviation_sd_units")
    assert run["result"] == expected_result, (
        f"Expected result {expected_result}, got {run['result']}"
    )


def assert_session_snapshot(
    session: Dict[str, Any],
    densitometer_id: str,
    calibration_generation: int,
    applied_lsc: float,
    applied_factor: float,
) -> None:
    assert session["densitometer_id"] == densitometer_id
    assert session["calibration_generation"] == calibration_generation
    assert_four_decimals(session["applied_lsc_g_cm2"], applied_lsc, "applied_lsc_g_cm2")
    assert_four_decimals(
        session["applied_cross_cal_factor"], applied_factor, "applied_cross_cal_factor"
    )


def assert_review_outcome(
    review: Dict[str, Any], severity: int, criterion_met: bool, outcome: str
) -> None:
    assert review["severity_score"] == severity, (
        f"Expected severity_score {severity}, got {review['severity_score']}"
    )
    assert review["repeat_criterion_met"] is criterion_met
    assert review["outcome"] == outcome, (
        f"Expected outcome {outcome}, got {review['outcome']}"
    )


def assert_counters(
    patient: Dict[str, Any], open_orders: int, lifetime_scans: int
) -> None:
    assert patient["open_scheduled_order_count"] == open_orders, (
        f"Expected open_scheduled_order_count {open_orders}, "
        f"got {patient['open_scheduled_order_count']}"
    )
    assert patient["lifetime_screening_scan_count"] == lifetime_scans, (
        f"Expected lifetime_screening_scan_count {lifetime_scans}, "
        f"got {patient['lifetime_screening_scan_count']}"
    )


# ── Collection assertions ───────────────────────────────────────────────────


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"Expected ids {expected_ids}, got {actual}"


def assert_contains_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = {row["id"] for row in rows}
    for expected in expected_ids:
        assert expected in actual, f"Expected id {expected} in {sorted(actual)}"


def assert_excludes_ids(rows: Iterable[Dict[str, Any]], excluded_ids: Iterable[str]) -> None:
    actual = {row["id"] for row in rows}
    for excluded in excluded_ids:
        assert excluded not in actual, f"Did not expect id {excluded} in {sorted(actual)}"
