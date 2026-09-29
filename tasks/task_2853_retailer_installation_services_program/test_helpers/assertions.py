"""Domain assertions for the Retailer Installation Services API."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import iso3


def round_half_up(value, places: int = 0):
    """Round half up, the only rounding method the programme uses."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


# ---------------------------------------------------------------------------
# Money and scores
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: int, field: str = "money field") -> None:
    """Money is an integer count of cents in responses as well as requests."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be a JSON integer count of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_score(actual: Any, expected: float, field: str = "score") -> None:
    """Scores and percentages carry exactly two decimal places."""
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{field}: expected {expected:.2f}, got {actual}"
    )


def assert_units(actual: Any, expected: float, field: str = "units") -> None:
    assert actual == pytest.approx(expected, abs=0.001), (
        f"{field}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def assert_instant(actual: Any, expected: str, field: str = "instant") -> None:
    """Compare two instants after canonicalising sub-second width."""
    assert actual is not None, f"{field} must not be null"
    assert iso3(actual) == iso3(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_instant_format(value: Any, field: str = "instant") -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 UTC, got {value!r}"
    assert value.endswith("Z") and "." in value, (
        f"{field} must carry three fractional digits, got {value!r}"
    )
    assert len(value.split(".")[1]) == 4, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common resource fields
# ---------------------------------------------------------------------------
def assert_versioned_entity(entity: Dict[str, Any], name: str = "entity") -> None:
    """A resource that carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"{name}.id must be a bare UUID"
    assert_instant_format(entity["created_at"], f"{name}.created_at")
    assert_instant_format(entity["updated_at"], f"{name}.updated_at")
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{name}.version must be a positive integer"
    )


def assert_ledger_row(event: Dict[str, Any], name: str = "ScorecardEvent") -> None:
    """A scorecard event carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(event["id"]), f"{name}.id must be a bare UUID"
    assert_instant_format(event["created_at"], f"{name}.created_at")
    assert "updated_at" not in event or event["updated_at"] is None, (
        f"{name} must not carry updated_at"
    )
    assert "version" not in event or event["version"] is None, (
        f"{name} must not carry version"
    )


def assert_version(entity: Dict[str, Any], expected: int,
                   name: str = "entity") -> None:
    assert entity["version"] == expected, (
        f"{name}.version: expected {expected}, got {entity['version']}"
    )


# ---------------------------------------------------------------------------
# Project invariants and dimensions
# ---------------------------------------------------------------------------
def assert_deposit_conservation(project: Dict[str, Any]) -> None:
    """`deposit_paid_cents` equals the sum of the four deposit buckets, always."""
    buckets = (
        project["deposit_held_cents"]
        + project["deposit_applied_cents"]
        + project["deposit_refunded_cents"]
        + project["deposit_forfeited_cents"]
    )
    assert project["deposit_paid_cents"] == buckets, (
        "deposit conservation broken: paid "
        f"{project['deposit_paid_cents']} != held {project['deposit_held_cents']} "
        f"+ applied {project['deposit_applied_cents']} "
        f"+ refunded {project['deposit_refunded_cents']} "
        f"+ forfeited {project['deposit_forfeited_cents']}"
    )


def assert_deposit_buckets(project: Dict[str, Any], paid: int, held: int, applied: int,
                           refunded: int, forfeited: int) -> None:
    assert_money(project["deposit_paid_cents"], paid, "deposit_paid_cents")
    assert_money(project["deposit_held_cents"], held, "deposit_held_cents")
    assert_money(project["deposit_applied_cents"], applied, "deposit_applied_cents")
    assert_money(project["deposit_refunded_cents"], refunded, "deposit_refunded_cents")
    assert_money(project["deposit_forfeited_cents"], forfeited,
                 "deposit_forfeited_cents")
    assert_deposit_conservation(project)


def assert_project_dimensions(project: Dict[str, Any],
                              fulfillment: Optional[str] = None,
                              financial: Optional[str] = None,
                              permit: Optional[str] = None) -> None:
    """The three status dimensions are asserted independently."""
    if fulfillment is not None:
        assert project["fulfillment_status"] == fulfillment, (
            f"fulfillment_status: expected {fulfillment}, "
            f"got {project['fulfillment_status']}"
        )
    if financial is not None:
        assert project["financial_status"] == financial, (
            f"financial_status: expected {financial}, "
            f"got {project['financial_status']}"
        )
    if permit is not None:
        assert project["permit_status"] == permit, (
            f"permit_status: expected {permit}, got {project['permit_status']}"
        )


# ---------------------------------------------------------------------------
# Installer invariants
# ---------------------------------------------------------------------------
def assert_committed_minutes(installer: Dict[str, Any], expected: int) -> None:
    assert installer["committed_minutes"] == expected, (
        f"committed_minutes: expected {expected}, "
        f"got {installer['committed_minutes']}"
    )


def assert_capacity_conservation(installer: Dict[str, Any],
                                 assignments: Iterable[Dict[str, Any]]) -> None:
    """`committed_minutes` equals the sum of `duration_minutes` over the installer's
    HELD, CONFIRMED, IN_PROGRESS and COMPLETED assignments."""
    live = {"HELD", "CONFIRMED", "IN_PROGRESS", "COMPLETED"}
    expected = sum(
        a["duration_minutes"] for a in assignments if a["status"] in live
    )
    assert installer["committed_minutes"] == expected, (
        f"capacity conservation broken: committed_minutes "
        f"{installer['committed_minutes']} != summed duration {expected}"
    )


def assert_scorecard_dimensions(installer: Dict[str, Any], quality: float,
                                timeliness: float, satisfaction: float,
                                composite: float) -> None:
    assert_score(installer["quality_score"], quality, "quality_score")
    assert_score(installer["timeliness_score"], timeliness, "timeliness_score")
    assert_score(installer["satisfaction_score"], satisfaction, "satisfaction_score")
    assert_score(installer["composite_score"], composite, "composite_score")


# ---------------------------------------------------------------------------
# Read-your-write and no-side-effect checks
# ---------------------------------------------------------------------------
def assert_same_fields(written: Dict[str, Any], read: Dict[str, Any],
                       fields: Iterable[str]) -> None:
    """Every derived field is final in the writing response itself."""
    for field in fields:
        assert written.get(field) == read.get(field), (
            f"{field} differs between the write response ({written.get(field)}) "
            f"and the subsequent read ({read.get(field)})"
        )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     fields: Iterable[str]) -> None:
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)} to {after.get(field)} "
            f"when it should not have moved"
        )
