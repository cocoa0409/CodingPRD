"""Domain assertion helpers.

The framework validators already unwrap the response envelope, so everything
here operates on a resource dictionary or on a raw response and never indexes
`["data"]` a second time.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant

_TOLERANCE = 1e-9


def _as_number(value: Any) -> float:
    assert value is not None, "Expected a numeric value, got null"
    if isinstance(value, bool):
        raise AssertionError(f"Expected a number, got boolean {value!r}")
    return float(value)


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a UUID id, both timestamps and an integer version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO-8601 instant, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be an ISO-8601 instant, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_created_defaults(entity: Dict[str, Any]) -> None:
    """A freshly created resource is at version 1 with updated_at == created_at."""
    assert_common_fields(entity, expected_version=1)
    assert canonical_instant(entity["updated_at"]) == canonical_instant(entity["created_at"]), (
        "updated_at must equal created_at at creation"
    )


def assert_three_fractional_digits(value: str) -> None:
    """An emitted instant carries exactly three fractional digits and a Z suffix."""
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    assert value.endswith("Z"), f"Instant must end in Z, got {value!r}"
    assert "." in value, f"Instant must carry fractional digits, got {value!r}"
    fraction = value.split(".", 1)[1][:-1]
    assert len(fraction) == 3, f"Instant must carry exactly three fractional digits: {value!r}"


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def assert_money_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """A `_cents` field is an integer count of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


def assert_decimal(actual: Any, expected: float, label: str = "value", places: int = 2) -> None:
    """A declared-precision decimal equals `expected` at `places` decimal places."""
    numeric = _as_number(actual)
    quantised = round(numeric, places)
    assert abs(quantised - round(expected, places)) < _TOLERANCE, (
        f"Expected {label} {expected:.{places}f}, got {numeric}"
    )
    assert abs(numeric - quantised) < _TOLERANCE, (
        f"{label} must carry at most {places} decimal places, got {numeric}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "max_compliance_ratio") -> None:
    """`max_compliance_ratio` is the one four-decimal quantity in the system."""
    assert_decimal(actual, expected, label=label, places=4)


def assert_is_null(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity.get(field, None) is None, f"Expected {field} to be null, got {entity[field]!r}"


def assert_equals(entity: Dict[str, Any], field: str, expected: Any) -> None:
    assert entity[field] == expected, f"Expected {field} == {expected!r}, got {entity[field]!r}"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants after normalising fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_same_members(actual: Any, expected: Sequence[Any], label: str = "array") -> None:
    assert isinstance(actual, list), f"{label} must be an array, got {actual!r}"
    assert sorted(actual) == sorted(expected), f"Expected {label} {sorted(expected)}, got {sorted(actual)}"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def assert_status(entity: Dict[str, Any], expected: str) -> None:
    assert entity["status"] == expected, f"Expected status {expected}, got {entity['status']}"


def assert_entry_point_posture(
    entry_point: Dict[str, Any],
    posture: Optional[str] = None,
    monitoring_status: Optional[str] = None,
    treatment_status: Optional[str] = None,
    accepted_result_count: Optional[int] = None,
    max_compliance_ratio: Optional[float] = None,
    hazard_index: Optional[float] = None,
    consecutive_qualifying_quarters: Optional[int] = None,
    consecutive_invalidated_samples: Optional[int] = None,
    open_violation_count: Optional[int] = None,
) -> None:
    """Assert any subset of the derived monitoring figures on an entry point."""
    if posture is not None:
        assert_equals(entry_point, "compliance_posture", posture)
    if monitoring_status is not None:
        assert_equals(entry_point, "monitoring_status", monitoring_status)
    if treatment_status is not None:
        assert_equals(entry_point, "treatment_status", treatment_status)
    if accepted_result_count is not None:
        assert_equals(entry_point, "accepted_result_count", accepted_result_count)
    if max_compliance_ratio is not None:
        assert_ratio(entry_point["max_compliance_ratio"], max_compliance_ratio)
    if hazard_index is not None:
        assert_decimal(entry_point["hazard_index"], hazard_index, label="hazard_index")
    if consecutive_qualifying_quarters is not None:
        assert_equals(
            entry_point, "consecutive_qualifying_quarters", consecutive_qualifying_quarters
        )
    if consecutive_invalidated_samples is not None:
        assert_equals(
            entry_point, "consecutive_invalidated_samples", consecutive_invalidated_samples
        )
    if open_violation_count is not None:
        assert_equals(entry_point, "open_violation_count", open_violation_count)


def assert_rate_ladder(
    project: Dict[str, Any],
    local_share_cents: Optional[int] = None,
    borrowed_cents: Optional[int] = None,
    annual_debt_service_cents: Optional[int] = None,
    base_annual_requirement_cents: Optional[int] = None,
    provisional_rate_impact_pct: Optional[float] = None,
    surcharge_bp: Optional[int] = None,
    final_annual_requirement_cents: Optional[int] = None,
    rate_impact_pct: Optional[float] = None,
    uniform_monthly_increase_cents: Optional[int] = None,
    volumetric_rate_increase_cents_per_kgal: Optional[int] = None,
    volumetric_monthly_increase_cents: Optional[int] = None,
    monthly_bill_increase_cents: Optional[int] = None,
) -> None:
    """Assert any subset of the seven ladder steps and the two bill variants."""
    integer_fields = {
        "local_share_cents": local_share_cents,
        "borrowed_cents": borrowed_cents,
        "annual_debt_service_cents": annual_debt_service_cents,
        "base_annual_requirement_cents": base_annual_requirement_cents,
        "surcharge_bp": surcharge_bp,
        "final_annual_requirement_cents": final_annual_requirement_cents,
        "uniform_monthly_increase_cents": uniform_monthly_increase_cents,
        "volumetric_rate_increase_cents_per_kgal": volumetric_rate_increase_cents_per_kgal,
        "volumetric_monthly_increase_cents": volumetric_monthly_increase_cents,
        "monthly_bill_increase_cents": monthly_bill_increase_cents,
    }
    for field, expected in integer_fields.items():
        if expected is not None:
            assert isinstance(project[field], int) and not isinstance(project[field], bool), (
                f"{field} must be an integer, got {project[field]!r}"
            )
            assert project[field] == expected, (
                f"Expected {field} {expected}, got {project[field]}"
            )
    if provisional_rate_impact_pct is not None:
        assert_decimal(
            project["provisional_rate_impact_pct"],
            provisional_rate_impact_pct,
            label="provisional_rate_impact_pct",
        )
    if rate_impact_pct is not None:
        assert_decimal(project["rate_impact_pct"], rate_impact_pct, label="rate_impact_pct")


def assert_allocation_buckets(claim: Dict[str, Any], *, investigation: int, capital: int, om_reserve: int, rate_stabilization: int, recovered: int) -> None:
    """The four settlement buckets sum to exactly the recovered amount."""
    assert_money_cents(claim["alloc_investigation_cents"], investigation, "alloc_investigation_cents")
    assert_money_cents(claim["alloc_capital_cents"], capital, "alloc_capital_cents")
    assert_money_cents(claim["alloc_om_reserve_cents"], om_reserve, "alloc_om_reserve_cents")
    assert_money_cents(
        claim["alloc_rate_stabilization_cents"], rate_stabilization, "alloc_rate_stabilization_cents"
    )
    total = investigation + capital + om_reserve + rate_stabilization
    assert total == recovered, f"Buckets sum to {total}, expected {recovered}"


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
def assert_total_count(response, expected: int) -> List[Dict[str, Any]]:
    """Assert a list response's `total_count` and return its rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_page(response, expected_total: int, expected_has_more: bool, expected_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Assert the pagination metadata and, optionally, the exact page contents."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"Expected total_count {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"Expected has_more {expected_has_more}, got {meta['has_more']}"
    )
    if expected_ids is not None:
        assert [row["id"] for row in rows] == list(expected_ids), (
            f"Expected page ids {list(expected_ids)}, got {[row['id'] for row in rows]}"
        )
    return rows


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not ordered by created_at ascending: {stamps}"


def first_row(response) -> Dict[str, Any]:
    """Return the single row of a list response asserted to hold exactly one."""
    rows = assert_total_count(response, 1)
    return rows[0]


def data_of(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a success envelope and return its `data` object."""
    return validate_success(response, expected_status)
