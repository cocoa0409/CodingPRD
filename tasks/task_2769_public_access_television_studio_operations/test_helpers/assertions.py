"""Domain assertion helpers built on the shared response validators.

These wrap the PRD's cross-field invariants so a test can state the rule once
rather than re-deriving it. Nothing here weakens an assertion: each helper
checks exactly what the PRD says and nothing looser.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import _canonical_instant


# --------------------------------------------------------------- primitives
def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants ignoring fractional-second width."""
    assert actual is not None, "expected {} to be {}, got null".format(field, expected)
    assert _canonical_instant(actual) == _canonical_instant(expected), (
        "expected {} to be {}, got {}".format(field, expected, actual)
    )


def assert_is_uuid(value: Any, field: str = "id") -> None:
    assert is_valid_uuid(value), "expected {} to be a bare UUID, got {!r}".format(field, value)


def assert_is_timestamp(value: Any, field: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        "expected {} to be an ISO 8601 UTC instant, got {!r}".format(field, value)
    )


def assert_cents(value: Any, expected: int, field: str) -> None:
    """Money is always a whole number of cents carried as a JSON integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "expected {} to be an integer number of cents, got {!r}".format(field, value)
    )
    assert value == expected, "expected {} to be {}, got {}".format(field, expected, value)


def assert_index_equals(value: Any, expected: float) -> None:
    """The community impact index is a JSON number carrying two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "expected community_impact_index to be a JSON number, got {!r}".format(value)
    )
    assert abs(float(value) - expected) < 0.005, (
        "expected community_impact_index {}, got {}".format(expected, value)
    )


# ----------------------------------------------------------- common fields
def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Identity and audit fields carried by every resource but the attestation."""
    assert_is_uuid(resource.get("id"))
    assert_is_timestamp(resource.get("created_at"), "created_at")
    assert_is_timestamp(resource.get("updated_at"), "updated_at")
    version = resource.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        "expected an integer version, got {!r}".format(version)
    )
    assert version >= 1, "version starts at 1, got {}".format(version)
    if expected_version is not None:
        assert version == expected_version, (
            "expected version {}, got {}".format(expected_version, version)
        )


def assert_attestation_shape(attestation: Dict[str, Any]) -> None:
    """An attestation is append-only: it carries an id and created_at only."""
    assert_is_uuid(attestation.get("id"))
    assert_is_timestamp(attestation.get("created_at"), "created_at")
    assert "updated_at" not in attestation, (
        "an append-only attestation must not carry updated_at"
    )
    assert "version" not in attestation, "an append-only attestation must not carry a version field"


# ------------------------------------------------------------- collections
def assert_pagination_meta(response, expected_total: Optional[int] = None):
    """Assert the four pagination fields and return ``(data, meta)``."""
    data, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            "expected total_count {}, got {}".format(expected_total, meta["total_count"])
        )
    return data, meta


def assert_ids_equal(items: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [item["id"] for item in items]
    assert actual == expected_ids, "expected ids {}, got {}".format(expected_ids, actual)


def assert_contains_id(items: List[Dict[str, Any]], expected_id: str) -> None:
    ids = [item["id"] for item in items]
    assert expected_id in ids, "expected {} among {}".format(expected_id, ids)


def assert_excludes_id(items: List[Dict[str, Any]], excluded_id: str) -> None:
    ids = [item["id"] for item in items]
    assert excluded_id not in ids, "expected {} to be absent from {}".format(excluded_id, ids)


# --------------------------------------------------- domain-level invariants
def assert_settlement_identities(reservation: Dict[str, Any]) -> None:
    """The two identities the PRD states hold on every settled reservation.

    The hold always equals the forfeited amount plus the refunded amount, and
    the forfeited amount plus the uncovered liability always equals the late fee
    plus the assessed repair.
    """
    hold = reservation["deposit_hold_cents"]
    forfeited = reservation["deposit_forfeited_cents"]
    refunded = reservation["deposit_refunded_cents"]
    uncovered = reservation["uncovered_liability_cents"]
    charges = reservation["late_fee_cents"] + reservation["assessed_repair_cents"]
    assert hold == forfeited + refunded, (
        "hold {} must equal forfeited {} plus refunded {}".format(hold, forfeited, refunded)
    )
    assert forfeited + uncovered == charges, (
        "forfeited {} plus uncovered {} must equal late fee plus repair {}".format(
            forfeited, uncovered, charges
        )
    )


def assert_allocation_identity(period: Dict[str, Any]) -> None:
    """The three allocations always sum back to the total program funds."""
    total = period["total_program_funds_cents"]
    parts = (
        period["admin_reserve_cents"]
        + period["capital_allocation_cents"]
        + period["operating_allocation_cents"]
    )
    assert parts == total, (
        "admin plus capital plus operating {} must equal total {}".format(parts, total)
    )
    assert total == period["allocable_base_cents"] + period["capital_grant_cents"], (
        "total {} must equal allocable base plus capital grant".format(total)
    )


def assert_channel_ledger(channel: Dict[str, Any], scheduled: int, aired: int) -> None:
    """Scheduled and aired seconds account for every booked second exactly once."""
    assert channel["scheduled_seconds"] == scheduled, (
        "expected scheduled_seconds {}, got {}".format(scheduled, channel["scheduled_seconds"])
    )
    assert channel["aired_seconds"] == aired, (
        "expected aired_seconds {}, got {}".format(aired, channel["aired_seconds"])
    )


def assert_producer_counters(
    producer: Dict[str, Any],
    held: Optional[int] = None,
    forfeited_total: Optional[int] = None,
    suspension_points: Optional[int] = None,
    volunteer_tenths: Optional[int] = None,
    commitments: Optional[int] = None,
) -> None:
    """Assert whichever derived producer counters a rule names."""
    if held is not None:
        assert_cents(producer["deposit_held_cents"], held, "deposit_held_cents")
    if forfeited_total is not None:
        assert_cents(
            producer["deposit_forfeited_total_cents"], forfeited_total,
            "deposit_forfeited_total_cents",
        )
    if suspension_points is not None:
        assert producer["suspension_points"] == suspension_points, (
            "expected suspension_points {}, got {}".format(
                suspension_points, producer["suspension_points"]
            )
        )
    if volunteer_tenths is not None:
        assert producer["volunteer_hours_tenths"] == volunteer_tenths, (
            "expected volunteer_hours_tenths {}, got {}".format(
                volunteer_tenths, producer["volunteer_hours_tenths"]
            )
        )
    if commitments is not None:
        assert producer["confirmed_crew_commitments"] == commitments, (
            "expected confirmed_crew_commitments {}, got {}".format(
                commitments, producer["confirmed_crew_commitments"]
            )
        )


def assert_field_absent_or_null(resource: Dict[str, Any], field: str) -> None:
    assert resource.get(field) is None, (
        "expected {} to be null, got {!r}".format(field, resource.get(field))
    )


def data_of(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate the success envelope and return the resource object."""
    return validate_success(response, expected_status)


def created_of(response) -> Dict[str, Any]:
    """Validate a 201 creation envelope and return the created resource."""
    return validate_success(response, 201)


def error_of(response, expected_error_id: str, expected_status: Optional[int] = None):
    """Validate a refusal, checking the identifier and its published status."""
    return validate_error(response, expected_error_id, expected_status)
