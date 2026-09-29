"""
Domain assertion helpers for the Child Support Enforcement API test suite.

These wrap the framework's structural assertions with the vocabulary of this
domain: the common audit stamps, the two immutable financial events that carry
neither ``updated_at`` nor ``version``, the allocation-waterfall invariants and
the pagination block of a list response.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .factories import format_instant_seconds, parse_instant

# ---------------------------------------------------------------------------
# Identity and audit stamps
# ---------------------------------------------------------------------------


def assert_identity(entity: Dict[str, Any]) -> None:
    """Assert the row carries a server-minted UUID id with no type prefix."""
    assert "id" in entity, "row is missing 'id'"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"


def assert_created_at(entity: Dict[str, Any]) -> None:
    """Assert ``created_at`` is an ISO 8601 UTC instant."""
    assert "created_at" in entity, "row is missing 'created_at'"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 UTC instant: {entity['created_at']!r}"
    )


def assert_versioned_row(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the row carries the full set of audit stamps: id, created_at,
    updated_at and an integer version.
    """
    assert_identity(entity)
    assert_created_at(entity)
    assert "updated_at" in entity, "versioned row is missing 'updated_at'"
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC instant: {entity['updated_at']!r}"
    )
    assert isinstance(entity.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_financial_event(entity: Dict[str, Any]) -> None:
    """
    Assert the row is one of the two immutable financial events: it carries
    ``id`` and ``created_at`` and carries neither ``updated_at`` nor ``version``.
    """
    assert_identity(entity)
    assert_created_at(entity)
    assert "updated_at" not in entity, (
        "an immutable financial event must not expose 'updated_at'"
    )
    assert "version" not in entity, (
        "an immutable financial event must not expose 'version'"
    )


# ---------------------------------------------------------------------------
# Field presence
# ---------------------------------------------------------------------------


def assert_absent(entity: Dict[str, Any], *field_names: str) -> None:
    """Assert each named field is absent, which a row may render as null."""
    for name in field_names:
        assert entity.get(name) is None, (
            f"expected {name} to be absent, got {entity.get(name)!r}"
        )


def assert_present(entity: Dict[str, Any], *field_names: str) -> None:
    """Assert each named field is present and not null."""
    for name in field_names:
        assert name in entity, f"row is missing {name}"
        assert entity[name] is not None, f"expected {name} to carry a value"


def assert_field_equals(entity: Dict[str, Any], field_name: str, expected: Any) -> None:
    """Assert one named field carries exactly the expected value."""
    assert field_name in entity, f"row is missing {field_name}"
    assert entity[field_name] == expected, (
        f"expected {field_name} == {expected!r}, got {entity[field_name]!r}"
    )


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert every named field carries exactly its expected value."""
    for name, value in expected.items():
        assert_field_equals(entity, name, value)


# ---------------------------------------------------------------------------
# Money and instants
# ---------------------------------------------------------------------------


def assert_money(entity: Dict[str, Any], field_name: str, expected_cents: int) -> None:
    """Assert a money field is an integer number of cents equal to ``expected_cents``."""
    assert field_name in entity, f"row is missing {field_name}"
    actual = entity[field_name]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field_name} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected_cents, (
        f"expected {field_name} == {expected_cents}, got {actual}"
    )


def assert_money_fields(entity: Dict[str, Any], **expected: int) -> None:
    """Assert several money fields at once."""
    for name, value in expected.items():
        assert_money(entity, name, value)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """
    Assert two ISO 8601 UTC instants name the same moment, tolerating a
    difference in how many fractional-second digits each one renders.
    """
    assert actual is not None, f"{label} is absent"
    assert format_instant_seconds(parse_instant(actual)) == format_instant_seconds(
        parse_instant(expected)
    ), f"expected {label} == {expected}, got {actual}"


def assert_date_equals(actual: Optional[str], expected: str, label: str = "date") -> None:
    """Assert a calendar date field equals the expected year-month-day string."""
    assert actual == expected, f"expected {label} == {expected}, got {actual!r}"


def assert_ratio_equals(actual: Any, expected: float, label: str = "ratio") -> None:
    """Assert a ratio or percentage carries exactly the expected numeric value."""
    assert actual is not None, f"{label} is absent"
    assert float(actual) == expected, f"expected {label} == {expected}, got {actual!r}"


# ---------------------------------------------------------------------------
# Status dimensions
# ---------------------------------------------------------------------------


def assert_case_dimensions(
    case: Dict[str, Any],
    case_status: Optional[str] = None,
    enforcement_posture: Optional[str] = None,
    interstate_role: Optional[str] = None,
) -> None:
    """Assert whichever of a case's three independent status dimensions are named."""
    if case_status is not None:
        assert_field_equals(case, "case_status", case_status)
    if enforcement_posture is not None:
        assert_field_equals(case, "enforcement_posture", enforcement_posture)
    if interstate_role is not None:
        assert_field_equals(case, "interstate_role", interstate_role)


def assert_iwo_dimensions(
    iwo: Dict[str, Any],
    service_status: Optional[str] = None,
    remittance_status: Optional[str] = None,
) -> None:
    """Assert whichever of a withholding order's two status dimensions are named."""
    if service_status is not None:
        assert_field_equals(iwo, "service_status", service_status)
    if remittance_status is not None:
        assert_field_equals(iwo, "remittance_status", remittance_status)


def assert_participant_remedy_flags(
    participant: Dict[str, Any],
    license_suspension_active: Optional[bool] = None,
    lien_recorded: Optional[bool] = None,
    credit_bureau_reported: Optional[bool] = None,
    has_valid_drivers_license: Optional[bool] = None,
) -> None:
    """Assert whichever of the obligor's remedy flags are named."""
    if license_suspension_active is not None:
        assert_field_equals(participant, "license_suspension_active", license_suspension_active)
    if lien_recorded is not None:
        assert_field_equals(participant, "lien_recorded", lien_recorded)
    if credit_bureau_reported is not None:
        assert_field_equals(participant, "credit_bureau_reported", credit_bureau_reported)
    if has_valid_drivers_license is not None:
        assert_field_equals(participant, "has_valid_drivers_license", has_valid_drivers_license)


# ---------------------------------------------------------------------------
# Allocation waterfall invariants
# ---------------------------------------------------------------------------

WATERFALL_BUCKETS = (
    "applied_current_cents",
    "applied_medical_cents",
    "applied_arrears_cents",
    "applied_interest_cents",
    "applied_genetic_cost_cents",
)


def assert_waterfall_buckets(payment: Dict[str, Any], **expected: int) -> None:
    """Assert the named allocation buckets of a payment."""
    for name, value in expected.items():
        assert_money(payment, name, value)


def assert_waterfall_exhausts_payment(payment: Dict[str, Any]) -> None:
    """
    Assert the applied buckets plus the unapplied credit sum to ``amount_cents``
    exactly, as the rounding-free waterfall requires.
    """
    total = sum(payment[name] for name in WATERFALL_BUCKETS)
    total += payment["unapplied_credit_cents"]
    assert total == payment["amount_cents"], (
        f"applied buckets {total} do not sum to amount_cents "
        f"{payment['amount_cents']}"
    )


def assert_distribution_invariant(payment: Dict[str, Any]) -> None:
    """
    Assert the disbursed share plus the retained share plus the unapplied credit
    equals ``amount_cents``.
    """
    total = (
        payment["disbursed_to_cp_cents"]
        + payment["retained_by_state_cents"]
        + payment["unapplied_credit_cents"]
    )
    assert total == payment["amount_cents"], (
        f"disbursed {payment['disbursed_to_cp_cents']} + retained "
        f"{payment['retained_by_state_cents']} + unapplied "
        f"{payment['unapplied_credit_cents']} != amount_cents "
        f"{payment['amount_cents']}"
    )


def assert_installment_schedule_sums(offer: Dict[str, Any]) -> None:
    """
    Assert the recurring installment multiplied by one fewer than the
    installment count, plus the final installment, equals the settlement total.
    """
    recurring = offer["monthly_installment_cents"] * (offer["installment_count"] - 1)
    assert recurring + offer["final_installment_cents"] == offer["settlement_total_cents"], (
        f"schedule {recurring} + {offer['final_installment_cents']} != "
        f"settlement total {offer['settlement_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Lists and pagination
# ---------------------------------------------------------------------------


def assert_pagination(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert whichever pagination fields of a list response are named."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_ids_equal(rows: List[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a list page carries exactly the expected ids in exactly that order."""
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"expected ids {expected}, got {actual}"


def assert_ascending_created_at(rows: List[Dict[str, Any]]) -> None:
    """Assert a list page is ordered oldest row first."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "list rows are not in ascending created_at order"


def assert_all_distinct(values: Iterable[Any], label: str = "values") -> None:
    """Assert every value in the collection is pairwise distinct."""
    collected = list(values)
    assert len(set(collected)) == len(collected), (
        f"expected {label} to be pairwise distinct, got {collected}"
    )
