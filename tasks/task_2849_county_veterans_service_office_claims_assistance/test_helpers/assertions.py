"""
Domain assertions for the County Veterans Service Office API.

Unwrapping convention, applied without exception across the suite: the
framework's validate_success()/validate_paginated() are the ONLY places the
envelope's `data` is unwrapped. Every helper below whose name does not end in
`_response` therefore takes an already-unwrapped resource dict. The handful of
helpers that must inspect the envelope itself take the raw response and are
named `..._response`.
"""

from typing import Any, Dict, List, Optional

import pytest
import requests
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    SCREEN_CATEGORY_KEYS,
)

# ─── Envelope-level helpers ───────────────────────────


def assert_created_response(response: requests.Response) -> Dict[str, Any]:
    """A creation returns HTTP 201 with the created resource in data."""
    return validate_success(response, 201)


def assert_ok_response(response: requests.Response) -> Dict[str, Any]:
    """A read, modification or lifecycle action returns HTTP 200."""
    return validate_success(response, 200)


def assert_pagination_mirror_response(
    response: requests.Response,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    A list endpoint reports the four pagination fields in meta and mirrors
    them in a sibling top-level pagination object with the same values.
    """
    assert response.status_code == 200, response.text
    body = response.json()
    meta = body["meta"]
    assert "pagination" in body, "List response must carry a top-level pagination object"
    pagination = body["pagination"]

    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta must carry {key}"
        assert key in pagination, f"pagination must carry {key}"
        assert pagination[key] == meta[key], (
            f"pagination.{key} ({pagination[key]!r}) must mirror "
            f"meta.{key} ({meta[key]!r})"
        )

    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_total is not None:
        assert meta["total_count"] == expected_total
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more
    return pagination


def assert_default_pagination_response(response: requests.Response) -> None:
    """An omitted limit defaults to 10 and an omitted offset defaults to 0."""
    assert response.status_code == 200, response.text
    meta = response.json()["meta"]
    assert meta["limit"] == DEFAULT_LIMIT
    assert meta["offset"] == DEFAULT_OFFSET


def assert_single_read_has_no_pagination_response(
    response: requests.Response,
) -> None:
    """Single-resource reads carry neither pagination fields nor the object."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert "pagination" not in body, (
        "Single-resource reads must not carry a pagination object"
    )
    meta = body["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, f"Single-resource meta must not carry {key}"


# ─── Identity and audit fields ────────────────────────


def assert_versioned_shape(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """The audit quartet carried by thirteen of the fourteen families."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity.get("created_at")
    assert is_iso8601_timestamp(entity["updated_at"]), entity.get("updated_at")
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_fresh_row(entity: Dict[str, Any]) -> None:
    """At creation version is 1 and updated_at equals created_at."""
    assert_versioned_shape(entity, expected_version=1)
    assert canonical_instant(entity["updated_at"]) == canonical_instant(
        entity["created_at"]
    ), "At creation updated_at equals created_at"


def assert_append_only_shape(screen: Dict[str, Any]) -> None:
    """A screen carries only id and created_at from the audit set."""
    assert is_valid_uuid(screen["id"]), screen.get("id")
    assert is_iso8601_timestamp(screen["created_at"]), screen.get("created_at")
    assert "updated_at" not in screen, "A screen has no updated_at field"
    assert "version" not in screen, "A screen has no version field"


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    assert entity["version"] == expected, (
        f"Expected version {expected}, got {entity['version']}"
    )


def assert_instant(value: Any) -> None:
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected!r}, got {actual!r}"
    )


def assert_date(value: Any) -> None:
    assert isinstance(value, str), f"Not a date string: {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"Date must be formatted YYYY-MM-DD: {value!r}"
    )


# ─── Numeric disciplines ──────────────────────────────


def assert_cents(actual: Any, expected: int) -> None:
    """Money is integer cents compared for exact equality."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"A _cents field must be an integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"Expected {expected} cents, got {actual}"


def assert_pct_2dp(actual: Any, expected: float) -> None:
    """A percentage carried to exactly two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {expected}, got {actual}"
    )


def assert_pct_1dp(actual: Any, expected: float) -> None:
    """A percentage carried to exactly one decimal place."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {expected}, got {actual}"
    )


def assert_weight_points(actual: Any, expected: float) -> None:
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected weight_points {expected}, got {actual}"
    )


def assert_exact_whole(actual: Any, expected: int, label: str = "value") -> None:
    """Whole numbers compared for exact equality with no tolerance."""
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


def assert_caseload_weight(actual: Any, expected: int) -> None:
    """caseload_weight is an exact integer reported in a numeric field."""
    assert float(actual) == float(expected), (
        f"Expected caseload_weight {expected}, got {actual}"
    )
    assert float(actual) == int(float(actual)), (
        f"caseload_weight must be an exact integer, got {actual}"
    )


def assert_combined_rating(actual: Any, expected: int) -> None:
    """combined_rating_pct is a multiple of 10 between 0 and 100 inclusive."""
    assert actual == expected, f"Expected combined_rating_pct {expected}, got {actual}"
    assert actual % 10 == 0, f"combined_rating_pct must be a multiple of 10: {actual}"
    assert 0 <= actual <= 100, f"combined_rating_pct out of range: {actual}"


# ─── Entity-shaped assertions ─────────────────────────


def assert_representative_defaults(rep: Dict[str, Any]) -> None:
    """A fresh roster row lands PENDING with three counters at zero."""
    assert rep["accreditation_status"] == "PENDING"
    assert rep["ce_credits_earned"] == 0
    assert rep["active_poa_count"] == 0
    assert_caseload_weight(rep["caseload_weight"], 0)
    assert rep.get("revocation_reason") is None


def assert_veteran_intake_defaults(veteran: Dict[str, Any]) -> None:
    """The placeholder values a brand-new intake record starts with."""
    assert veteran["intake_status"] == "INTAKE_STARTED"
    assert veteran["discharge_doc_status"] == "NOT_SUBMITTED"
    assert veteran["character_of_service"] == "UNCHARACTERIZED"
    assert veteran["wartime_service_days"] == 0
    assert veteran["combined_rating_pct"] == 0
    assert veteran["priority_group"] == "P4"
    assert veteran.get("assigned_representative_id") is None
    assert veteran.get("date_of_death") is None


def assert_case_number_format(case_number: str, year: int, sequence: int) -> None:
    """county_case_number is CVSO- year - six-digit zero-padded sequence."""
    assert case_number == f"CVSO-{year}-{sequence:06d}", (
        f"Expected CVSO-{year}-{sequence:06d}, got {case_number!r}"
    )


def assert_screen_categories(screen: Dict[str, Any]) -> None:
    """category_results always carries exactly the six declared keys."""
    results = screen["category_results"]
    assert set(results.keys()) == set(SCREEN_CATEGORY_KEYS), (
        f"category_results keys must be exactly {SCREEN_CATEGORY_KEYS}, "
        f"got {sorted(results.keys())}"
    )
    for key, entry in results.items():
        assert set(entry.keys()) >= {"eligible", "reason"}, (
            f"category_results[{key}] must carry eligible and reason"
        )
        assert isinstance(entry["eligible"], bool)
        assert isinstance(entry["reason"], str)


def assert_category_eligible(screen: Dict[str, Any], key: str, expected: bool) -> None:
    actual = screen["category_results"][key]["eligible"]
    assert actual is expected, (
        f"Expected {key} eligible={expected}, got {actual}"
    )


def assert_application_filing_defaults(application: Dict[str, Any]) -> None:
    """A successful filing commits no money at all."""
    assert application["determination_status"] == "SUBMITTED"
    assert application["disbursement_status"] == "NOT_APPLICABLE"
    assert_cents(application["gross_award_cents"], 0)
    assert_cents(application["admin_fee_cents"], 0)
    assert_cents(application["benefit_amount_cents"], 0)


def assert_caseload_decomposition(
    payload: Dict[str, Any],
    representative_id: str,
    active_poa_count: int,
    open_claim_count: int,
    planned_outreach_count: int,
    caseload_weight: int,
    assignment_eligible: Optional[bool] = None,
) -> None:
    """The workload read exposes exactly the terms the sum is built from."""
    assert payload["representative_id"] == representative_id
    assert_exact_whole(payload["active_poa_count"], active_poa_count, "active_poa_count")
    assert_exact_whole(payload["open_claim_count"], open_claim_count, "open_claim_count")
    assert_exact_whole(
        payload["planned_outreach_count"], planned_outreach_count, "planned_outreach_count"
    )
    assert_caseload_weight(payload["caseload_weight"], caseload_weight)
    if assignment_eligible is not None:
        assert payload["assignment_eligible"] is assignment_eligible


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    """Locate one row of a list payload by its id."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"Row {row_id} not present in list of {len(rows)}")


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


__all__ = [
    "assert_created_response",
    "assert_ok_response",
    "assert_pagination_mirror_response",
    "assert_default_pagination_response",
    "assert_single_read_has_no_pagination_response",
    "assert_versioned_shape",
    "assert_fresh_row",
    "assert_append_only_shape",
    "assert_version_is",
    "assert_instant",
    "assert_instant_equals",
    "assert_date",
    "assert_cents",
    "assert_pct_2dp",
    "assert_pct_1dp",
    "assert_weight_points",
    "assert_exact_whole",
    "assert_caseload_weight",
    "assert_combined_rating",
    "assert_representative_defaults",
    "assert_veteran_intake_defaults",
    "assert_case_number_format",
    "assert_screen_categories",
    "assert_category_eligible",
    "assert_application_filing_defaults",
    "assert_caseload_decomposition",
    "find_by_id",
    "ids_of",
]
