"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime.

    Comparing instants rather than raw strings keeps assertions stable across
    the equivalent ``...T00:00:00Z`` / ``...T00:00:00.000Z`` serializations.
    """
    assert isinstance(value, str) and value, f"expected a timestamp string, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_eq(actual, expected_iso: str, label: str = "timestamp"):
    """Assert two timestamps denote the same instant."""
    assert actual is not None, f"{label}: expected {expected_iso}, got null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "resource"):
    """The four system-managed properties every resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )


def assert_partner(data: dict):
    assert_common_fields(data, "Partner")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE"), data["status"]
    assert data["fee_tier"] in ("TIER_A", "TIER_B", "TIER_C"), data["fee_tier"]
    assert data["industry"] in ("TECH", "FINANCE", "HEALTHCARE", "RETAIL", "LOGISTICS")
    assert isinstance(data["credit_hold"], bool), data["credit_hold"]
    for field in ("outstanding_balance_cents", "billed_cents", "collected_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents, got {data[field]!r}"


def assert_partner_billing_zeroed(data: dict):
    """A freshly registered partner carries no receivables at all (PRD §3.3)."""
    assert data["outstanding_balance_cents"] == 0, data["outstanding_balance_cents"]
    assert data["billed_cents"] == 0, data["billed_cents"]
    assert data["collected_cents"] == 0, data["collected_cents"]
    assert float(data["collection_ratio"]) == 0.0, data["collection_ratio"]
    assert float(data["on_time_payment_ratio"]) == 0.0, data["on_time_payment_ratio"]
    assert data["credit_hold"] is False, data["credit_hold"]
    assert data["oldest_open_due_date"] is None, data["oldest_open_due_date"]


def assert_student(data: dict):
    assert_common_fields(data, "Student")
    assert data["application_state"] in ("APPLIED", "ELIGIBLE", "INELIGIBLE", "ENROLLED")
    assert data["current_phase"] in (None, "L_AND_D", "INTERNSHIP", "COMPLETED")
    assert data["roster_status"] in ("ON_TRACK", "PROBATION", "DISMISSED")
    for field in ("total_stipend_paid_cents", "lifetime_contract_points", "conversion_streak"):
        assert isinstance(data[field], int), f"{field} must be an integer, got {data[field]!r}"


def assert_cohort(data: dict):
    assert_common_fields(data, "Cohort")
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED"), data["status"]
    assert data["program_code"] in ("SOFTWARE", "DATA", "CYBER", "IT_SUPPORT")
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["awarded_points"], int)


def assert_agreement(data: dict):
    assert_common_fields(data, "Agreement")
    assert data["status"] in ("DRAFT", "ACTIVE", "FULFILLED"), data["status"]
    assert data["fee_tier"] in ("TIER_A", "TIER_B", "TIER_C"), data["fee_tier"]
    assert isinstance(data["supervision_hours_per_week"], int)
    assert isinstance(data["slot_count"], int)


def assert_placement(data: dict):
    assert_common_fields(data, "InternshipPlacement")
    assert data["state"] in (
        "MATCHED", "INTERVIEW_SCHEDULED", "INTERVIEWED", "OFFERED",
        "ACCEPTED", "ACTIVE", "COMPLETED", "TERMINATED",
    ), data["state"]
    assert isinstance(data["interview_attempt"], int)
    assert data.get("outcome") in (None, "CONVERTED", "NOT_CONVERTED"), data.get("outcome")


def assert_interview_round(data: dict):
    assert_common_fields(data, "InterviewRound")
    assert data["outcome"] in ("PENDING", "PASSED", "FAILED"), data["outcome"]
    assert isinstance(data["round_number"], int)
    assert isinstance(data["duration_minutes"], int)


def assert_stipend_statement(data: dict):
    assert_common_fields(data, "StipendStatement")
    assert data["status"] in ("PENDING", "PAID", "VOID"), data["status"]
    assert data["phase"] in ("L_AND_D", "INTERNSHIP"), data["phase"]
    for field in (
        "gross_amount_cents", "attendance_deduction_cents",
        "behavior_deduction_cents", "net_amount_cents", "contract_points_earned",
    ):
        assert isinstance(data[field], int), f"{field} must be integer, got {data[field]!r}"
    assert 0 <= float(data["attendance_ratio"]) <= 1.0, data["attendance_ratio"]


def assert_satisfaction_record(data: dict):
    assert_common_fields(data, "SatisfactionRecord")
    assert 0.0 <= float(data["composite_score"]) <= 5.0, data["composite_score"]
    assert isinstance(data.get("converted_to_hire"), bool), data.get("converted_to_hire")


def assert_outcome_checkpoint(data: dict):
    assert_common_fields(data, "OutcomeCheckpoint")
    assert data["employment_status"] in (
        "UNKNOWN", "EMPLOYED", "UNEMPLOYED", "ENROLLED_EDUCATION"
    ), data["employment_status"]


def assert_invoice(data: dict):
    assert_common_fields(data, "Invoice")
    assert data["status"] in ("ISSUED", "OVERDUE", "PAID", "VOID"), data["status"]
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_credit_grant(data: dict):
    assert_common_fields(data, "CreditGrant")
    assert data["status"] in ("PENDING", "GRANTED", "VOID"), data["status"]
    assert isinstance(data["tuition_credit_cents"], int)
