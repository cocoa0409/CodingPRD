"""Domain assertion helpers.

These operate on the payload a validator has already returned, so nothing here
re-reaches into an envelope: by the time a body arrives it is the ``data`` value
itself, and unwrapping it a second time would be wrong.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

# Tolerance for the two-decimal quantities the PRD rounds to hundredths.
TWO_DP = 0.005


# ─── Structural shape (PRD §2.4) ──────────────────────

def assert_identifier(entity: Dict[str, Any]) -> None:
    """A resource identifier is a bare UUID string."""
    assert "id" in entity, f"Missing 'id' on {entity!r}"
    assert is_valid_uuid(entity["id"]), f"'id' is not a bare UUID: {entity['id']!r}"


def assert_created_stamp(entity: Dict[str, Any]) -> None:
    """``created_at`` is an ISO-8601 UTC instant with exactly three fractional digits."""
    assert "created_at" in entity, f"Missing 'created_at' on {entity!r}"
    value = entity["created_at"]
    assert is_iso8601_timestamp(value), f"'created_at' is not ISO-8601 UTC: {value!r}"
    assert value.endswith("Z"), f"'created_at' must be UTC-suffixed: {value!r}"
    fraction = value[:-1].split(".")
    assert len(fraction) == 2 and len(fraction[1]) == 3, (
        f"'created_at' must carry exactly three fractional digits: {value!r}"
    )


def assert_versioned_entity(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A mutable entity carries id, created_at, updated_at and a version."""
    assert_identifier(entity)
    assert_created_stamp(entity)
    assert "updated_at" in entity, f"Missing 'updated_at' on {entity!r}"
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"'updated_at' is not ISO-8601 UTC: {entity['updated_at']!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"'version' must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"'version' starts at 1, got {entity['version']}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_entity(entity: Dict[str, Any]) -> None:
    """An immutable record carries only an identifier and a birth stamp.

    Neither an ``updated_at`` nor a ``version`` may appear, because the record is
    written once and never revised.
    """
    assert_identifier(entity)
    assert_created_stamp(entity)
    assert "updated_at" not in entity, (
        f"An immutable record must not expose 'updated_at': {entity!r}"
    )
    assert "version" not in entity, (
        f"An immutable record must not expose 'version': {entity!r}"
    )


# ─── Envelope meta (PRD §2.2) ─────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Check the request-correlation fields every envelope carries."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    stamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(stamp), f"api_request_timestamp not ISO-8601: {stamp!r}"
    assert stamp.endswith("Z") and len(stamp.split(".")[-1]) == 4, (
        f"api_request_timestamp needs exactly three fractional digits: {stamp!r}"
    )


def assert_list_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """Check the pagination block a collection response carries."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"Missing pagination field '{key}' in {meta!r}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )


# ─── Numeric precision (PRD §2.6) ─────────────────────

def assert_two_decimal_value(value: Any, expected: float, label: str = "value") -> None:
    """Compare a hundredths-rounded quantity against its expected value."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert value == pytest.approx(expected, abs=TWO_DP), (
        f"Expected {label} {expected}, got {value}"
    )


def assert_integer_cents(value: Any, expected: Optional[int] = None, label: str = "cents") -> None:
    """Money is carried as an integer number of cents, never a fraction or a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"Expected {label} {expected}, got {value}"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 instants as moments, ignoring sub-second spelling width."""
    assert actual is not None, f"{label} is missing"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_instant_absent(entity: Dict[str, Any], field: str) -> None:
    """A stamp that has not been reached yet reads as null."""
    assert entity.get(field) is None, (
        f"Expected '{field}' to be null, got {entity.get(field)!r}"
    )


# ─── Field-by-field comparison ────────────────────────

def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Compare a set of expected field values against an entity body.

    Floating-point fields are compared to hundredths and instants are compared as
    moments, so a difference in spelling never masquerades as a difference in value.
    """
    for field, want in expected.items():
        assert field in entity, f"Missing field '{field}' in {entity!r}"
        got = entity[field]
        if isinstance(want, float):
            assert_two_decimal_value(got, want, label=field)
        elif isinstance(want, str) and is_iso8601_timestamp(want):
            assert_instant_equals(got, want, label=field)
        else:
            assert got == want, f"Expected {field} {want!r}, got {got!r}"


def assert_absent(entity: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is either missing or explicitly null."""
    for field in fields:
        assert entity.get(field) is None, (
            f"Expected '{field}' to be null, got {entity.get(field)!r}"
        )


# ─── Ordering (PRD §2.3) ──────────────────────────────

def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    """Assert a listing is sorted on one field in the stated direction."""
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"Rows are not ordered by {field} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def assert_id_sequence(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert a listing returns exactly these rows, in exactly this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"Expected row order {list(expected_ids)}, got {actual}"
    )


def assert_contains_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert every expected identifier appears somewhere in a listing."""
    actual = {row["id"] for row in rows}
    missing = [i for i in expected_ids if i not in actual]
    assert not missing, f"Listing is missing {missing}; it returned {sorted(actual)}"


def assert_excludes_ids(rows: Iterable[Dict[str, Any]], excluded_ids: Iterable[str]) -> None:
    """Assert none of these identifiers appears in a listing."""
    actual = {row["id"] for row in rows}
    present = [i for i in excluded_ids if i in actual]
    assert not present, f"Listing should not contain {present}"


# ─── Read models ──────────────────────────────────────

def assert_workload(
    workload: Dict[str, Any],
    available_hours: Optional[float] = None,
    projected_load_hours: Optional[float] = None,
    projected_utilization_pct: Optional[float] = None,
    realized_load_hours: Optional[float] = None,
    realized_utilization_pct: Optional[float] = None,
    casework_training_ratio: Optional[float] = None,
    active_assignment_count: Optional[int] = None,
    assigned_casework_hours: Optional[float] = None,
) -> None:
    """Compare a workload projection against its expected figures."""
    numeric = {
        "available_hours": available_hours,
        "projected_load_hours": projected_load_hours,
        "projected_utilization_pct": projected_utilization_pct,
        "realized_load_hours": realized_load_hours,
        "realized_utilization_pct": realized_utilization_pct,
        "casework_training_ratio": casework_training_ratio,
        "assigned_casework_hours": assigned_casework_hours,
    }
    for field, want in numeric.items():
        if want is not None:
            assert field in workload, f"Missing '{field}' in workload {workload!r}"
            assert_two_decimal_value(workload[field], want, label=field)
    if active_assignment_count is not None:
        assert workload["active_assignment_count"] == active_assignment_count, (
            f"Expected active_assignment_count {active_assignment_count}, "
            f"got {workload['active_assignment_count']}"
        )


def assert_backlog_report(
    report: Dict[str, Any],
    open_request_count: Optional[int] = None,
    backlog_index: Optional[float] = None,
    bucket_0_29_count: Optional[int] = None,
    bucket_30_59_count: Optional[int] = None,
    bucket_60_89_count: Optional[int] = None,
    bucket_90_plus_count: Optional[int] = None,
    p1_open_count: Optional[int] = None,
    outsourcing_recommended: Optional[bool] = None,
    as_of_utc: Optional[str] = None,
) -> None:
    """Compare a backlog reading against its expected figures."""
    if backlog_index is not None:
        assert_two_decimal_value(report["backlog_index"], backlog_index, "backlog_index")
    integers = {
        "open_request_count": open_request_count,
        "bucket_0_29_count": bucket_0_29_count,
        "bucket_30_59_count": bucket_30_59_count,
        "bucket_60_89_count": bucket_60_89_count,
        "bucket_90_plus_count": bucket_90_plus_count,
        "p1_open_count": p1_open_count,
    }
    for field, want in integers.items():
        if want is not None:
            assert report[field] == want, (
                f"Expected {field} {want}, got {report[field]}"
            )
    if outsourcing_recommended is not None:
        assert report["outsourcing_recommended"] is outsourcing_recommended, (
            f"Expected outsourcing_recommended {outsourcing_recommended}, "
            f"got {report['outsourcing_recommended']!r}"
        )
    if as_of_utc is not None:
        assert_instant_equals(report["as_of_utc"], as_of_utc, "as_of_utc")


def assert_vendor_ledger(
    vendor: Dict[str, Any],
    encumbered_cents: Optional[int] = None,
    spent_cents: Optional[int] = None,
) -> None:
    """Compare a vendor's two ledger columns against their expected balances."""
    if encumbered_cents is not None:
        assert_integer_cents(vendor["encumbered_cents"], encumbered_cents, "encumbered_cents")
    if spent_cents is not None:
        assert_integer_cents(vendor["spent_cents"], spent_cents, "spent_cents")


def assert_pricing_chain(
    engagement: Dict[str, Any],
    base_amount_cents: int,
    rush_surcharge_cents: int,
    tier_basis_cents: int,
    volume_discount_pct: float,
    discount_amount_cents: int,
    award_amount_cents: int,
) -> None:
    """Compare every pinned step of the award pricing chain."""
    assert_integer_cents(engagement["base_amount_cents"], base_amount_cents, "base_amount_cents")
    assert_integer_cents(
        engagement["rush_surcharge_cents"], rush_surcharge_cents, "rush_surcharge_cents"
    )
    assert_integer_cents(engagement["tier_basis_cents"], tier_basis_cents, "tier_basis_cents")
    assert_two_decimal_value(
        engagement["volume_discount_pct"], volume_discount_pct, "volume_discount_pct"
    )
    assert_integer_cents(
        engagement["discount_amount_cents"], discount_amount_cents, "discount_amount_cents"
    )
    assert_integer_cents(
        engagement["award_amount_cents"], award_amount_cents, "award_amount_cents"
    )


def collect_ids(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """Identifiers of a listing, in the order the listing returned them."""
    return [row["id"] for row in rows]
