"""Domain assertions for the Public Records Data Journalism Desk API.

These wrap the framework validators with the invariants this PRD states
explicitly: the conserved fee-budget identity of PRD S2.7, the finding-count
partition of PRD S3.7, the whole-day deadline stamping of PRD S2.6, the
three-fractional-digit audit timestamps of PRD S2.4, and the absence of
``updated_at``/``version`` on ``Agency`` (PRD S2.4).
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from . import constants as C
from .api_client import canonical_instant

__all__ = [
    "validate_created",
    "validate_ok",
    "validate_unpaginated",
    "validate_paginated_page",
    "validate_error",
    "assert_instant_equals",
    "assert_audit_timestamp_format",
    "assert_deadline_stamp",
    "assert_ledger_identity",
    "assert_ledger_columns",
    "assert_finding_partition",
    "assert_partition_counts",
    "assert_version_is",
    "assert_agency_has_no_mutable_common_fields",
    "assert_has_common_fields",
    "round_half_up",
    "assert_ids_in_order",
    "assert_field_absent_or_null",
]

# An ISO-8601 UTC instant with exactly three fractional digits (PRD S2.4).
_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# --------------------------------------------------------------------------
# Envelope helpers
# --------------------------------------------------------------------------


def validate_created(response) -> Dict[str, Any]:
    """Assert a 201 creation envelope and return the created resource.

    PRD S4: "Endpoints that bring a new resource into existence return HTTP
    201".
    """
    return validate_success(response, expected_status=201)


def validate_ok(response) -> Dict[str, Any]:
    """Assert a 200 envelope and return ``data``.

    PRD S4: "every other successful call ... returns HTTP 200".
    """
    return validate_success(response, expected_status=200)


def validate_paginated_page(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Assert a paginated list envelope and return ``(rows, meta)``.

    Use this for the list endpoints of PRD S4, whose ``meta`` block "carries
    ``limit``, ``offset``, ``total_count`` ... and ``has_more``" (PRD S2.3).
    """
    return validate_paginated(response)


def validate_unpaginated(response, expected_status: int = 200) -> List[Dict[str, Any]]:
    """Assert an array envelope *without* requiring the pagination meta block.

    Some array-valued responses in this API are not list endpoints in the sense
    of PRD S2.3 -- they are the array payload of a single resource -- and the
    pagination fields of PRD S2.3 are only promised "for list endpoints"
    (PRD S2.2). This validator therefore asserts the envelope and the array
    shape and leaves ``meta`` alone.
    """
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status}, got {response.status_code}: "
        f"{response.text[:400]}"
    )
    body = response.json()
    assert "meta" in body, f"response envelope has no meta: {body}"
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    data = body.get("data")
    assert isinstance(data, list), f"expected data to be a list, got {type(data)}"
    return data


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 strings denote the same instant.

    Compared as instants, never as strings: PRD S2.4 pins a three-digit
    fractional width only on the audit timestamps, so a stamped deadline may
    legitimately come back with a different fractional width.
    """
    assert actual is not None, f"{label} is null; expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_audit_timestamp_format(value: str, label: str = "created_at") -> None:
    """Assert the exact audit-timestamp format of PRD S2.4.

    PRD S2.4: ``created_at`` is "an ISO 8601 UTC timestamp with exactly three
    fractional digits".
    """
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _THREE_FRACTIONAL_DIGITS.match(value), (
        f"{label} must be an ISO-8601 UTC instant with exactly three fractional "
        f"digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} is not a valid ISO-8601 instant"


def assert_deadline_stamp(actual: str, expected_date: str, label: str = "deadline") -> None:
    """Assert a whole-day deadline stamp (PRD S2.6).

    PRD S2.6: "a due instant is the ISO date produced by advancing the start
    date by the required number of days on the agency's basis, with the
    time-of-day component set to exactly ``23:59:59.000Z``".

    ``expected_date`` is a ``YYYY-MM-DD`` string.
    """
    assert_instant_equals(
        actual, f"{expected_date}T{C.DEADLINE_TIME_OF_DAY}", label=label
    )
    assert actual.endswith(C.DEADLINE_TIME_OF_DAY), (
        f"{label} must be stamped at exactly {C.DEADLINE_TIME_OF_DAY}, got {actual}"
    )


# --------------------------------------------------------------------------
# The conserved fee-budget identity (PRD S2.7)
# --------------------------------------------------------------------------


def assert_ledger_identity(desk: Dict[str, Any]) -> None:
    """Assert the conserved quantity of PRD S2.7 with no drift.

    PRD S2.7: "the total equals the sum of the available, committed and spent
    columns", and "none may ever go negative".
    """
    total = desk["fee_budget_total_cents"]
    available = desk["fee_budget_available_cents"]
    committed = desk["fee_budget_committed_cents"]
    spent = desk["fee_budget_spent_cents"]
    for name, value in (
        ("fee_budget_total_cents", total),
        ("fee_budget_available_cents", available),
        ("fee_budget_committed_cents", committed),
        ("fee_budget_spent_cents", spent),
    ):
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be an integer number of cents, got {value!r}"
        )
        assert value >= 0, f"{name} must never go negative, got {value}"
    assert total == available + committed + spent, (
        "conserved ledger identity violated: total "
        f"{total} != available {available} + committed {committed} + spent {spent}"
    )


def assert_ledger_columns(
    desk: Dict[str, Any],
    total: int,
    available: int,
    committed: int,
    spent: int,
) -> None:
    """Assert all four ledger columns and then the conserved identity."""
    assert desk["fee_budget_total_cents"] == total, (
        f"fee_budget_total_cents: expected {total}, "
        f"got {desk['fee_budget_total_cents']}"
    )
    assert desk["fee_budget_available_cents"] == available, (
        f"fee_budget_available_cents: expected {available}, "
        f"got {desk['fee_budget_available_cents']}"
    )
    assert desk["fee_budget_committed_cents"] == committed, (
        f"fee_budget_committed_cents: expected {committed}, "
        f"got {desk['fee_budget_committed_cents']}"
    )
    assert desk["fee_budget_spent_cents"] == spent, (
        f"fee_budget_spent_cents: expected {spent}, "
        f"got {desk['fee_budget_spent_cents']}"
    )
    assert_ledger_identity(desk)


# --------------------------------------------------------------------------
# The finding-count partition (PRD S3.7)
# --------------------------------------------------------------------------


def assert_finding_partition(investigation: Dict[str, Any]) -> None:
    """Assert the partition invariant of PRD S3.7.

    PRD S3.7: "``finding_count`` equals the sum of
    ``unverified_finding_count``, ``doc_matched_finding_count``,
    ``sme_confirmed_finding_count`` and ``sme_disputed_finding_count``".
    """
    total = investigation["finding_count"]
    unverified = investigation["unverified_finding_count"]
    doc_matched = investigation["doc_matched_finding_count"]
    confirmed = investigation["sme_confirmed_finding_count"]
    disputed = investigation["sme_disputed_finding_count"]
    assert total == unverified + doc_matched + confirmed + disputed, (
        f"finding partition violated: finding_count {total} != "
        f"unverified {unverified} + doc_matched {doc_matched} + "
        f"confirmed {confirmed} + disputed {disputed}"
    )


def assert_partition_counts(
    investigation: Dict[str, Any],
    finding_count: int,
    unverified: int,
    doc_matched: int,
    confirmed: int,
    disputed: int,
) -> None:
    """Assert every bucket of the partition, then the invariant itself."""
    assert investigation["finding_count"] == finding_count, (
        f"finding_count: expected {finding_count}, "
        f"got {investigation['finding_count']}"
    )
    assert investigation["unverified_finding_count"] == unverified, (
        f"unverified_finding_count: expected {unverified}, "
        f"got {investigation['unverified_finding_count']}"
    )
    assert investigation["doc_matched_finding_count"] == doc_matched, (
        f"doc_matched_finding_count: expected {doc_matched}, "
        f"got {investigation['doc_matched_finding_count']}"
    )
    assert investigation["sme_confirmed_finding_count"] == confirmed, (
        f"sme_confirmed_finding_count: expected {confirmed}, "
        f"got {investigation['sme_confirmed_finding_count']}"
    )
    assert investigation["sme_disputed_finding_count"] == disputed, (
        f"sme_disputed_finding_count: expected {disputed}, "
        f"got {investigation['sme_disputed_finding_count']}"
    )
    assert_finding_partition(investigation)


# --------------------------------------------------------------------------
# Versioning and common fields (PRD S2.4)
# --------------------------------------------------------------------------


def assert_version_is(resource: Dict[str, Any], expected: int, label: str = "resource") -> None:
    """Assert an exact ``version``.

    PRD S2.4: ``version`` "starts at 1 on creation and increases by exactly 1 on
    every mutation of the row".
    """
    assert resource.get("version") == expected, (
        f"{label} version: expected {expected}, got {resource.get('version')}"
    )


def assert_has_common_fields(resource: Dict[str, Any], label: str = "resource") -> None:
    """Assert the identity/audit/version fields every versioned row carries."""
    assert is_valid_uuid(resource["id"]), (
        f"{label} id must be a UUID string with no type prefix, got {resource['id']!r}"
    )
    assert_audit_timestamp_format(resource["created_at"], f"{label}.created_at")
    assert_audit_timestamp_format(resource["updated_at"], f"{label}.updated_at")
    assert isinstance(resource["version"], int) and not isinstance(
        resource["version"], bool
    ), f"{label}.version must be an integer, got {resource['version']!r}"


def assert_agency_has_no_mutable_common_fields(agency: Dict[str, Any]) -> None:
    """Assert the ``Agency`` exception of PRD S2.4.

    PRD S2.4: "``Agency`` is the single exception ... it carries only ``id`` and
    ``created_at``. It has no ``updated_at``, no ``version``, and no update
    endpoint at all."
    """
    assert is_valid_uuid(agency["id"]), (
        f"agency id must be a UUID string, got {agency['id']!r}"
    )
    assert_audit_timestamp_format(agency["created_at"], "agency.created_at")
    assert "updated_at" not in agency, (
        f"agency must expose no updated_at, got {agency.get('updated_at')!r}"
    )
    assert "version" not in agency, (
        f"agency must expose no version, got {agency.get('version')!r}"
    )


def assert_field_absent_or_null(
    resource: Dict[str, Any], field: str, label: str = "resource"
) -> None:
    """Assert a nullable field is either absent or explicitly null."""
    assert resource.get(field) is None, (
        f"{label}.{field}: expected null, got {resource.get(field)!r}"
    )


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def assert_ids_in_order(
    rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str], label: str = "rows"
) -> None:
    """Assert a listing returned exactly these ids in exactly this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"{label}: expected ids {list(expected_ids)}, got {actual}"
    )


# --------------------------------------------------------------------------
# Rounding (PRD S2.10)
# --------------------------------------------------------------------------


def round_half_up(value) -> int:
    """Round half up exactly as PRD S2.10 defines it.

    PRD S2.10: "add one half to the exact decimal product and truncate toward
    zero, which for these non-negative quantities means a fractional part of
    exactly one half always rounds away from zero".
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
