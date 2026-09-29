"""Record assertions, instant comparison helpers and domain invariant checkers."""

import re

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$"
)


# ─── Instant comparison ───────────────────────────────

def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to whole-second form.

    Fractional-second width is a serialisation detail, so a value carrying
    `.000`, `.0` or no fraction at all compares equal here. Any fractional
    part that is not zero is preserved so a genuinely different instant still
    compares unequal.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, fraction = match.groups()
    if fraction and int(fraction) != 0:
        return f"{date_part}T{time_part}.{fraction.rstrip('0')}Z"
    return f"{date_part}T{time_part}Z"


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two ISO 8601 UTC instants ignoring fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected!r}, got {actual!r}"
    )


def assert_audit_fields(data: dict, expected_version=None):
    """Every record type but the public comment carries these four fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


# ─── Record assertions ────────────────────────────────

def assert_health_service_area(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["population_projection"], int)
    assert data["population_projection"] >= 1
    assert isinstance(data["existing_licensed_beds"], int)
    assert data["existing_licensed_beds"] >= 0
    assert isinstance(data["approved_unimplemented_beds"], int)
    assert data["approved_unimplemented_beds"] >= 0
    assert isinstance(data["capital_authorization_committed_cents"], int)
    assert data["capital_authorization_committed_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_state_plan_formula(data: dict):
    assert_audit_fields(data)
    assert data["service_type"] in (
        "ACUTE_CARE_BEDS", "NURSING_HOME_BEDS", "PSYCHIATRIC_BEDS",
        "MRI_UNIT", "OPEN_HEART_SURGERY",
    )
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["effective_from_date"])
    assert data["use_rate_per_1000"] > 0
    assert data["average_length_of_stay_days"] > 0
    assert 0 < data["base_target_occupancy_rate"] < 1
    assert 0 < data["high_volume_target_occupancy_rate"] < 1
    assert data["high_volume_bed_threshold"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_hearing_room(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["seating_capacity"] >= 1
    assert isinstance(data["setup_buffer_minutes"], int)
    assert data["setup_buffer_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_applicant(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["organization_type"] in (
        "HOSPITAL", "NURSING_FACILITY", "PHYSICIAN_GROUP", "OTHER",
    )
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["standing"] in ("GOOD", "RESTRICTED", "BARRED")
    assert isinstance(data["compliance_strike_count"], int)
    assert data["compliance_strike_count"] >= 0


def assert_letter_of_intent(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["hsa_id"])
    assert is_valid_uuid(data["batching_cycle_id"])
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["status"] in (
        "FILED", "WITHDRAWN", "EXPIRED", "CONVERTED", "INELIGIBLE",
    )
    assert isinstance(data["capital_cost_cents"], int)
    assert data["capital_cost_cents"] >= 0
    assert isinstance(data["bed_delta"], int) and data["bed_delta"] >= 0
    assert isinstance(data["project_basis_reviewable"], bool)
    assert isinstance(data["aggregated_basis_reviewable"], bool)
    assert isinstance(data["prior_window_loi_count"], int)
    assert isinstance(data["aggregate_capital_cost_cents"], int)
    assert isinstance(data["aggregate_bed_delta"], int)
    assert data["governing_review_basis"] in ("PROJECT_BASED", "AGGREGATED_24_MONTH")
    assert data["review_determination"] in ("REVIEWABLE", "NON_REVIEWABLE")


def assert_batching_cycle(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["hsa_id"])
    assert is_valid_uuid(data["formula_id"])
    assert data["status"] in (
        "ANNOUNCED", "OPEN_FOR_LOI", "OPEN_FOR_APPLICATIONS",
        "COMPLETENESS_WINDOW", "COMPARATIVE_REVIEW", "DECIDED", "CLOSED",
    )
    for field in (
        "loi_deadline_at", "application_deadline_at", "comment_period_closes_at",
        "intervention_deadline_at", "completeness_deadline_at", "decision_deadline_at",
    ):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    assert isinstance(data["pinned_formula_version"], int)
    assert isinstance(data["required_beds_final"], int)
    assert isinstance(data["inventory_beds_at_open"], int)
    assert isinstance(data["unmet_bed_need_at_open"], int)
    assert isinstance(data["unallocated_bed_need"], int)
    assert data["unallocated_bed_need"] >= 0
    assert isinstance(data["reopened_count"], int)


def assert_application(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["loi_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["batching_cycle_id"])
    assert data["requested_bed_count"] >= 1
    assert isinstance(data["projected_capital_cost_cents"], int)
    assert data["projected_capital_cost_cents"] >= 0
    assert isinstance(data["partial_award_acceptable"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "COMPLETENESS_REVIEW", "INCOMPLETE",
        "DEEMED_COMPLETE", "COMPARATIVE_REVIEW", "APPROVED",
        "APPROVED_WITH_CONDITIONS", "DENIED", "REMANDED", "WITHDRAWN",
    )
    assert isinstance(data["score_sheet_count"], int)
    assert isinstance(data["allocated_bed_count"], int)
    assert data["allocated_bed_count"] >= 0
    assert isinstance(data["completeness_round_count"], int)
    if data["denial_reason"] is not None:
        assert data["denial_reason"] in (
            "INSUFFICIENT_NEED", "FAILED_CRITERIA", "APPEAL_REVERSED",
        )
    if data["status"] not in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        assert data["allocated_bed_count"] == 0, (
            "allocated_bed_count is 0 unless the application is approved"
        )


def assert_completeness_review(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ("DEFICIENCY_NOTICE_ISSUED", "CURED", "EXPIRED")
    assert isinstance(data["deficiency_items"], list)
    assert len(data["deficiency_items"]) >= 1
    assert is_iso8601_timestamp(data["cure_deadline_at"])
    assert isinstance(data["issued_by_user_id"], str)


def assert_public_comment(data: dict):
    """A comment is append-only: only id and created_at are system fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        "a public comment carries no updated_at"
    )
    assert "version" not in data, "a public comment carries no version"
    assert data["stance"] in ("SUPPORT", "OPPOSE", "NEUTRAL")
    assert isinstance(data["commenter_display_name"], str)
    assert isinstance(data["body"], str)
    assert is_iso8601_timestamp(data["filed_at"])


def assert_intervention(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["affected_party_applicant_id"])
    assert isinstance(data["grounds"], str)
    assert isinstance(data["requested_hearing"], bool)
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")
    assert is_iso8601_timestamp(data["filed_at"])


def assert_public_hearing(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["batching_cycle_id"])
    assert is_valid_uuid(data["hearing_room_id"])
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert is_iso8601_timestamp(data["occupancy_start_at"])
    assert data["status"] in ("SCHEDULED", "CANCELLED", "HELD")
    assert isinstance(data["reschedule_count"], int)


def assert_score_sheet(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["reviewer_user_id"], str)
    for field in (
        "need_conformity_score", "financial_feasibility_score",
        "cost_containment_score", "access_underserved_score",
        "quality_record_score",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert 0 <= data[field] <= 100, f"{field} must lie between 0 and 100"
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "STALE")


def assert_certificate(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["approved_expenditure_limit_cents"], int)
    assert data["approved_expenditure_limit_cents"] >= 1
    assert isinstance(data["expenditure_ceiling_cents"], int)
    assert data["expenditure_basis"] in ("CASH", "ACCRUAL")
    assert isinstance(data["authorized_bed_count"], int)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["implementation_milestone_date"])
    assert 0 <= data["required_completion_pct_at_milestone"] <= 100
    assert isinstance(data["conditions"], list)
    assert data["lifecycle_status"] in (
        "ISSUED", "IMPLEMENTED", "SUSPENDED", "LAPSED", "REVOKED", "SUPERSEDED",
    )
    assert data["expenditure_status"] in (
        "WITHIN_LIMIT", "OVER_LIMIT_PENDING_AMENDMENT",
        "LIMIT_BREACHED", "LIMIT_AMENDED",
    )
    assert isinstance(data["cumulative_expenditure_cash_cents"], int)
    assert isinstance(data["cumulative_expenditure_accrual_cents"], int)
    assert 0 <= data["latest_completion_pct"] <= 100
    assert isinstance(data["extension_days_granted_total"], int)
    assert isinstance(data["issued_by_user_id"], str)


def assert_progress_report(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["certificate_id"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["period_end_date"])
    assert isinstance(data["disbursed_cents"], int) and data["disbursed_cents"] >= 0
    assert isinstance(data["obligated_cents"], int) and data["obligated_cents"] >= 0
    assert 0 <= data["physical_completion_pct"] <= 100
    assert isinstance(data["condition_attestations"], list)
    assert data["status"] in ("ACCEPTED", "SUPERSEDED")
    assert isinstance(data["filed_by_user_id"], str)


def assert_appeal(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["appellant_applicant_id"])
    assert isinstance(data["grounds"], str)
    assert data["status"] in (
        "FILED", "BRIEFING", "STAYED", "HEARD", "AFFIRMED", "REVERSED", "REMANDED",
    )
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["litigation_hold_active"], bool)


# ─── Domain invariant checkers ────────────────────────

def assert_cycle_pool_invariant(cycle: dict, applications: list):
    """`unallocated_bed_need` plus every awarded bed equals the opening pool."""
    awarded = sum(
        app["allocated_bed_count"]
        for app in applications
        if app["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS")
    )
    assert cycle["unallocated_bed_need"] + awarded == cycle["unmet_bed_need_at_open"], (
        f"Pool invariant broken: unallocated {cycle['unallocated_bed_need']} + "
        f"awarded {awarded} != opening pool {cycle['unmet_bed_need_at_open']}"
    )


def assert_expenditure_ceiling(certificate: dict):
    """The ceiling is the limit multiplied by 1.05, rounded half up to a cent."""
    limit = certificate["approved_expenditure_limit_cents"]
    from decimal import Decimal, ROUND_HALF_UP

    expected = int(
        (Decimal(limit) * Decimal("1.05")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert certificate["expenditure_ceiling_cents"] == expected, (
        f"Expected ceiling {expected}, got {certificate['expenditure_ceiling_cents']}"
    )


def assert_score(actual, expected):
    """Compare a comparative score carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected comparative_score {expected}, got {actual}"
    )


def assert_four_decimal_value(actual, expected):
    """Compare a need-methodology intermediate carried to four decimals."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"Expected {expected} to four decimal places, got {actual}"
    )
