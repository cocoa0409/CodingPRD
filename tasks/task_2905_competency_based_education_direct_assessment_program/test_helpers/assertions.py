"""Entity assertions, instant comparison helpers and domain invariant checkers."""
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

# ─── Instants ─────────────────────────────────────────────────────────────────

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$")


def normalize_instant(value: str) -> str:
    """Canonicalise an ISO 8601 UTC instant to exactly three fractional digits.

    The PRD fixes the transport form at three fractional digits, so a response
    that echoes a different fractional width is still the same instant; this
    helper lets a test compare instants without depending on the width.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 instant, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    seconds, fraction = match.group(1), (match.group(2) or "")
    fraction = (fraction + "000")[:3]
    return f"{seconds}.{fraction}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_present(actual: Any, label: str = "instant") -> None:
    assert actual is not None, f"{label} must be set"
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC: {actual!r}"


# ─── Numbers ──────────────────────────────────────────────────────────────────

def assert_number_equals(actual: Any, expected: float, label: str) -> None:
    """Compare a decimal-scaled numeric field. Never accepts a string."""
    assert not isinstance(actual, str), (
        f"{label} must be a JSON number, not the string {actual!r}"
    )
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert float(actual) == pytest.approx(float(expected), abs=1e-6), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str) -> None:
    """Money is always an integer number of cents, never a string, never
    fractional."""
    assert not isinstance(actual, str), (
        f"{label} must be a JSON number of cents, not the string {actual!r}"
    )
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert float(actual) == float(int(actual)), f"{label} must be whole cents: {actual}"
    assert int(actual) == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_decimal_scale(value: Any, places: int, label: str) -> None:
    assert value is not None, f"{label} must not be null"
    quantised = Decimal(str(value)).quantize(Decimal(1).scaleb(-places))
    assert Decimal(str(value)) == quantised, (
        f"{label} carries more than {places} decimal places: {value}"
    )


# ─── Lists ────────────────────────────────────────────────────────────────────

def validate_list(response) -> Tuple[List[dict], dict]:
    """Peel a list response once. Returns (items, data).

    List endpoints put ``items``, ``total_count`` and ``has_more`` inside
    ``data``; the same pagination values also appear in ``meta``.
    """
    data, meta = validate_paginated(response)
    assert isinstance(data, dict), (
        f"A list endpoint's data must be an object carrying items, got {type(data)}"
    )
    assert isinstance(data.get("items"), list), "data.items must be an array"
    assert isinstance(data.get("total_count"), int), "data.total_count must be an int"
    assert isinstance(data.get("has_more"), bool), "data.has_more must be a boolean"
    return data["items"], data


def assert_page(response, expected_total: int, expected_count: Optional[int] = None,
                expected_has_more: Optional[bool] = None) -> List[dict]:
    items, data = validate_list(response)
    assert data["total_count"] == expected_total, (
        f"total_count: expected {expected_total}, got {data['total_count']}"
    )
    if expected_count is not None:
        assert len(items) == expected_count, (
            f"page size: expected {expected_count} rows, got {len(items)}"
        )
    if expected_has_more is not None:
        assert data["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {data['has_more']}"
        )
    return items


# ─── Common fields ────────────────────────────────────────────────────────────

def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None
                         ) -> None:
    """Every entity except the append-only progress checkpoint carries id,
    created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert_instant_present(data.get("created_at"), "created_at")
    assert_instant_present(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"version: expected {expected_version}, got {data['version']}"
        )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 16
    assert data["code"] == data["code"].upper(), "program code is uppercase"
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert isinstance(data["competency_count"], int)
    for field in ("mastery_threshold_pct", "units_per_credit_hour",
                  "irr_tolerance_pct", "irr_suspend_rate_pct",
                  "critical_dimension_min_ratio", "aid_earned_pct_full_threshold"):
        assert not isinstance(data[field], str), f"{field} must be a JSON number"
    if data["status"] == "DRAFT":
        assert data["published_at_utc"] is None, "published_at_utc is null while DRAFT"
    else:
        assert_instant_present(data["published_at_utc"], "published_at_utc")


def assert_competency(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert data["level"] in ("FOUNDATION", "CORE", "CAPSTONE")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert not isinstance(data["unit_value"], str), "unit_value must be a JSON number"
    assert data["unit_value"] > 0
    assert isinstance(data["prerequisite_depth"], int)
    assert isinstance(data["mastered_by_student_count"], int)
    assert not isinstance(data["effective_mastery_threshold_pct"], str)


def assert_blueprint(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["competency_id"])
    assert re.match(r"^BP-\d+$", data["version_label"]), (
        f"version_label must be BP-<n>: {data['version_label']!r}"
    )
    dims = data["dimensions"]
    assert isinstance(dims, list) and 1 <= len(dims) <= 8
    assert data["dimension_count"] == len(dims)
    codes = [d["code"] for d in dims]
    assert len(set(codes)) == len(codes), "dimension codes are unique"
    total = sum(Decimal(str(d["weight"])) for d in dims)
    assert total == Decimal("1.0000"), f"dimension weights must sum to 1.0000, got {total}"
    assert data["passing_rule"] in ("WEIGHTED_ONLY", "WEIGHTED_PLUS_ALL_CRITICAL")
    assert data["required_evaluator_count"] in (1, 2)
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")
    assert_instant_present(data["effective_from_utc"], "effective_from_utc")
    assert isinstance(data["attempts_bound_count"], int)


def assert_student(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["enrollment_status"] in (
        "APPLICANT", "ACTIVE", "SUSPENDED", "WITHDRAWN", "GRADUATED"
    )
    assert data["sap_status"] in (
        "GOOD_STANDING", "WARNING", "PROBATION", "DISMISSED"
    )
    for field in ("mastered_unit_total", "mastered_competency_count",
                  "cumulative_credit_equivalency", "integrity_strike_count"):
        assert not isinstance(data[field], str), f"{field} must be a JSON number"
    for field in ("aid_scheduled_total_cents", "aid_retained_total_cents",
                  "aid_returned_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_subscription_term(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in ("PENDING", "ACTIVE", "COMPLETED", "LAPSED", "CANCELLED")
    assert isinstance(data["tuition_cents"], int), "tuition_cents must be integer cents"
    assert isinstance(data["term_days"], int) and data["term_days"] > 0
    assert isinstance(data["attempts_used"], int)
    assert isinstance(data["credit_equivalency_earned"], int)
    assert_instant_present(data["term_start_utc"], "term_start_utc")
    assert_instant_present(data["term_end_utc"], "term_end_utc")
    assert normalize_instant(data["term_end_utc"]) > normalize_instant(
        data["term_start_utc"]
    ), "term_end_utc must be strictly after term_start_utc"


def assert_mentor(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] > 0
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] > 0
    assert isinstance(data["current_caseload"], int) and data["current_caseload"] >= 0
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "INACTIVE")


def assert_mentor_assignment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["mentor_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["selection_mode"] in ("EXPLICIT", "AUTO_SELECTED")
    assert data["status"] in ("ACTIVE", "ENDED")
    assert data["cadence_status"] in ("COMPLIANT", "OVERDUE")
    assert isinstance(data["overdue_days"], int) and data["overdue_days"] >= 0
    assert isinstance(data["contact_count"], int)
    assert isinstance(data["endorsement_count"], int)
    assert isinstance(data["endorsed_competency_ids"], list)
    assert_instant_present(data["assigned_at_utc"], "assigned_at_utc")
    assert_instant_present(data["next_contact_due_utc"], "next_contact_due_utc")


def assert_evaluator(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["certification_level"] in ("ASSOCIATE", "SENIOR")
    assert data["status"] in ("CERTIFIED", "PROVISIONAL", "SUSPENDED")
    for field in ("submitted_score_count", "paired_review_count",
                  "agreeing_review_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert not isinstance(data["irr_agreement_rate_pct"], str)


def assert_attempt(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["competency_id"])
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "ADJUDICATION", "INTEGRITY_HOLD",
        "REVISION_REQUESTED", "SCORED_MASTERED", "SCORED_NOT_MASTERED", "VOIDED",
    )
    assert data["held_from_status"] in (
        None, "DRAFT", "UNDER_REVIEW", "ADJUDICATION"
    )
    assert isinstance(data["integrity_hold"], bool)
    assert isinstance(data["integrity_attestation_accepted"], bool)
    assert isinstance(data["scores_received_count"], int)
    assert isinstance(data["is_provisional_score"], bool)
    assert isinstance(data["critical_fail"], bool)
    assert isinstance(data["revision_count"], int)
    assert data["score_variant"] in (
        None, "SINGLE_READER_FINAL", "PROVISIONAL_SINGLE_READER",
        "TWO_READER_MEAN", "ADJUDICATED",
    )
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_evaluator_score(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["attempt_id"])
    assert is_valid_uuid(data["evaluator_id"])
    assert data["reader_ordinal"] in (1, 2, 3)
    assert isinstance(data["is_adjudication"], bool)
    assert data["is_adjudication"] is (data["reader_ordinal"] == 3)
    assert data["status"] in ("SUBMITTED", "VOIDED")
    assert data["voided_reason"] in (None, "REVISION_REQUESTED", "ATTEMPT_VOIDED")
    if data["status"] == "SUBMITTED":
        assert data["voided_reason"] is None
    assert not isinstance(data["weighted_score_pct"], str)
    assert isinstance(data["critical_fail"], bool)


def assert_integrity_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["attempt_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["signal_type"] in (
        "SHARED_DEVICE", "DUPLICATE_ARTIFACT", "ATTESTATION_ANOMALY",
        "THIRD_PARTY_REPORT",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in (
        "OPEN", "UNDER_INVESTIGATION", "SUBSTANTIATED", "DISMISSED"
    )
    assert data["sanction"] in ("NONE", "ATTEMPT_VOID", "TERM_SUSPENSION")
    assert isinstance(data["auto_raised"], bool)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_sap_review(data: Dict[str, Any]) -> None:
    """A progress checkpoint is an append-only audit event: it carries only id
    and created_at, so it must expose neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert_instant_present(data.get("created_at"), "created_at")
    assert "updated_at" not in data, (
        "a progress checkpoint carries no updated_at"
    )
    assert "version" not in data, "a progress checkpoint carries no version"
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["term_id"])
    assert isinstance(data["terms_counted"], int)
    assert data["pace_band"] in ("GOOD", "WARN", "PROB", "FAIL")
    assert data["previous_sap_status"] in (
        "GOOD_STANDING", "WARNING", "PROBATION", "DISMISSED"
    )
    assert data["new_sap_status"] in (
        "GOOD_STANDING", "WARNING", "PROBATION", "DISMISSED"
    )
    assert_instant_present(data["evaluated_at_utc"], "evaluated_at_utc")


def assert_aid_disbursement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["term_id"])
    assert data["status"] in (
        "SCHEDULED", "HELD", "DISBURSED", "RETURNED", "CANCELLED"
    )
    assert data["hold_reason"] in (
        None, "CREDIT_EQUIVALENCY_SHORTFALL", "TERM_CLOSED", "INTEGRITY_REVIEW"
    )
    for field in ("scheduled_amount_cents", "outstanding_amount_cents",
                  "disbursed_amount_cents", "cancelled_amount_cents",
                  "returned_amount_cents", "retained_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["aid_review_required"], bool)
    assert data["scheduled_amount_cents"] > 0


def assert_transcript_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["purpose"] in ("TRANSFER", "INTERNAL", "STUDENT_COPY")
    assert data["status"] in ("DRAFT", "ISSUED", "VOIDED")
    assert data["voided_reason"] in (None, "UNIT_TOTAL_CHANGED", "SUPERSEDED")
    assert isinstance(data["lines"], list)
    assert data["competency_line_count"] == len(data["lines"]), (
        "competency_line_count is the number of lines"
    )
    for field in ("total_mastered_units", "translated_credit_hours",
                  "line_credit_hour_sum", "rounding_residual_credit_hours"):
        assert not isinstance(data[field], str), f"{field} must be a JSON number"


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_aid_ledger_identity(award: Dict[str, Any]) -> None:
    """The ledger identity the PRD requires to hold exactly after every aid
    transition."""
    status = award["status"]
    scheduled = award["scheduled_amount_cents"]
    if status in ("SCHEDULED", "HELD"):
        assert award["outstanding_amount_cents"] == scheduled
        assert award["retained_amount_cents"] == 0
        assert award["returned_amount_cents"] == 0
        assert award["cancelled_amount_cents"] == 0
    elif status == "DISBURSED":
        assert award["outstanding_amount_cents"] == 0
        assert award["retained_amount_cents"] == scheduled
        assert award["returned_amount_cents"] == 0
        assert award["cancelled_amount_cents"] == 0
    elif status == "RETURNED":
        assert award["outstanding_amount_cents"] == 0
        assert award["cancelled_amount_cents"] == 0
        assert award["returned_amount_cents"] == award["school_return_share_cents"]
        assert award["retained_amount_cents"] == (
            scheduled - award["school_return_share_cents"]
        )
    elif status == "CANCELLED":
        assert award["outstanding_amount_cents"] == 0
        assert award["retained_amount_cents"] == 0
        assert award["returned_amount_cents"] == 0
        assert award["cancelled_amount_cents"] == scheduled


def assert_return_split_is_exact(award: Dict[str, Any]) -> None:
    """The school's and the student's shares sum to exactly the unearned amount
    with no rounding residue."""
    assert (
        award["school_return_share_cents"] + award["student_return_share_cents"]
        == award["unearned_aid_cents"]
    ), "the two return shares must sum to unearned_aid_cents exactly"
    assert award["school_return_share_cents"] >= 0
    assert award["student_return_share_cents"] >= 0


def assert_progress_summary_shape(summary: Dict[str, Any]) -> None:
    for field in (
        "student_id", "enrollment_status", "sap_status", "mastered_unit_total",
        "mastered_competency_count", "required_unit_total",
        "cumulative_credit_equivalency", "aid_credit_equivalency_sum",
        "credit_equivalency_variance", "aid_scheduled_total_cents",
        "aid_retained_total_cents", "aid_returned_total_cents",
        "active_mentor_assignment_id", "cadence_status", "overdue_days",
        "open_integrity_case_count",
    ):
        assert field in summary, f"the progress summary must report {field}"
    assert isinstance(summary["overdue_days"], int)
    assert isinstance(summary["open_integrity_case_count"], int)


def assert_credit_equivalency_variance(summary: Dict[str, Any]) -> None:
    """The variance is the cumulative transcript figure minus the summed per-term
    aid figure."""
    expected = round(
        float(summary["cumulative_credit_equivalency"])
        - float(summary["aid_credit_equivalency_sum"]),
        1,
    )
    assert_number_equals(
        summary["credit_equivalency_variance"], expected, "credit_equivalency_variance"
    )
