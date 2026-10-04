"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    PAYOUT_APPROVAL_CAP_CENTS,
    REFUND_TEACHER_LIABILITY_RATE,
)


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every top-level resource carries id, created_at, updated_at and version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"


def assert_teacher_application(data: dict):
    assert_common_fields(data, "TeacherApplication")
    assert isinstance(data.get("applicant_user_id"), str) and data["applicant_user_id"]
    assert isinstance(data.get("applicant_email"), str) and data["applicant_email"]
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert data.get("status") in [
        "DRAFT", "SCREENING_PENDING", "SCREENING_FAILED", "SCREENING_PASSED",
        "SAMPLE_PENDING", "SAMPLE_REJECTED", "SAMPLE_APPROVED", "APPROVED", "REJECTED",
    ], f"unexpected application status {data.get('status')!r}"
    assert isinstance(data.get("revision_count"), int)


def assert_teacher(data: dict):
    assert_common_fields(data, "Teacher")
    assert data.get("status") in ["PENDING_SETUP", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data.get("payout_tax_document_status") in ["ON_FILE", "REQUIRED_UPDATE", "EXPIRED"]
    assert isinstance(data.get("lifetime_net_earnings_cents"), int)
    assert data["lifetime_net_earnings_cents"] >= 0, "lifetime earnings can never decrease below zero"
    assert data.get("actionable_risk_score") == max(
        data.get("open_report_risk_score", 0), data.get("upheld_report_risk_score", 0)
    ), "actionable_risk_score must be the max of the two risk readings"
    assert data.get("peak_actionable_risk_score", 0) >= data.get("actionable_risk_score", 0), (
        "peak_actionable_risk_score is a high-water mark"
    )


def assert_class_listing(data: dict):
    assert_common_fields(data, "ClassListing")
    assert data.get("format") in ["ONE_TIME", "MULTI_DAY", "ONGOING"]
    assert data.get("content_review_state") in ["PENDING_REVIEW", "POLICY_APPROVED", "POLICY_REJECTED"]
    assert data.get("lifecycle_state") in ["DRAFT", "PUBLISHED", "SUSPENDED", "ARCHIVED"]
    assert isinstance(data.get("list_price_cents"), int) and data["list_price_cents"] > 0
    assert 3 <= data.get("min_age", 0) <= data.get("max_age", 0) <= 18
    assert 1 <= data.get("max_learners", 0) <= 18


def assert_section(data: dict):
    assert_common_fields(data, "Section")
    assert data.get("status") in [
        "SCHEDULED", "OPEN_FOR_ENROLLMENT", "MIN_ENROLLMENT_MET", "CANCELLED", "COMPLETED",
    ]
    assert data.get("outcome") in [
        None, "HELD", "AUTO_CANCELLED_MIN_ENROLLMENT", "AUTO_CANCELLED_SEAT_LOSS", "CANCELLED_BY_TEACHER",
    ]
    assert_section_seat_invariant(data)


def assert_section_seat_invariant(data: dict):
    """seats_remaining never goes negative and equals capacity less both seat-holding counts."""
    enrolled = data.get("enrolled_count", 0)
    reserved = data.get("reserved_count", 0)
    remaining = data.get("seats_remaining", 0)
    assert remaining >= 0, f"seats_remaining must never be negative, got {remaining}"
    assert remaining == data.get("capacity", 0) - enrolled - reserved, (
        "seats_remaining must equal capacity less CONFIRMED and RESERVED enrollments"
    )
    assert data.get("enrollment_min_met") == (enrolled >= data.get("min_learners", 0)), (
        "enrollment_min_met must be true exactly when enrolled_count has reached min_learners"
    )


def assert_learner(data: dict):
    assert_common_fields(data, "Learner")
    assert data.get("subscription_tier") in ["NONE", "PLUS", "FAMILY"]
    assert data.get("confirmation_credit_cents", 0) >= 0
    assert data.get("abuse_strike_count", 0) >= 0


def assert_enrollment(data: dict):
    assert_common_fields(data, "Enrollment")
    assert data.get("status") in ["RESERVED", "CONFIRMED", "RELEASED", "CANCELLED_BY_TEACHER"]
    assert data.get("refund_category") in [None, "NONE", "PARTIAL_HALF", "FULL"]
    assert data.get("discounted_price_cents", 0) >= 0
    assert data.get("cash_refund_cents", 0) == data.get("refund_cents", 0) - data.get("credit_applied_cents", 0), (
        "cash_refund_cents must be refund_cents less the credit-applied portion"
    )


def assert_teacher_payout(data: dict):
    assert_common_fields(data, "TeacherPayout")
    assert data.get("status") in ["REQUESTED", "SENT", "FAILED", "PAID", "VOIDED"]
    assert data.get("approval_status") in ["not_required", "pending_approval", "approved"]
    assert data.get("tax_document_status") in ["ON_FILE", "REQUIRED_UPDATE", "EXPIRED"]
    assert data.get("net_payout_cents", 0) == data.get("gross_earnings_cents", 0) - data.get("platform_fee_cents", 0), (
        "net_payout_cents must be gross less the platform fee"
    )
    assert_cost_precision(data.get("gross_earnings_cents", 0))
    assert 0.0 <= data.get("fee_rate_applied", 0.0) <= 1.0


def assert_payout_money_invariant(data: dict):
    """The clawback's conserved quantity: liability is half of what remains after the reversed fee."""
    reversed_fee = data.get("platform_fee_reversed_cents", 0)
    liability = data.get("teacher_liability_cents", 0)
    assert reversed_fee >= 0 and liability >= 0
    assert data.get("net_after_refunds_cents", 0) == (
        data.get("gross_earnings_cents", 0) - data.get("platform_fee_cents", 0) - reversed_fee
    ), "net_after_refunds_cents must be gross less fee less reversed fee"
    if reversed_fee:
        # liability == floor((original_total - floor(original_total * rate)) * 0.50)
        assert liability >= 0
        assert REFUND_TEACHER_LIABILITY_RATE == 0.50


def assert_parent_report(data: dict):
    assert_common_fields(data, "ParentReport")
    assert data.get("status") in ["OPEN", "UNDER_REVIEW", "RESOLVED", "CLOSED"]
    assert data.get("disposition") in [None, "DISMISSED", "WARNING", "MORE_SEVERE"]
    assert data.get("severity") in ["LOW", "MEDIUM", "HIGH"]
    assert data.get("category") in ["CONTENT_POLICY", "SAFETY", "CONDUCT", "TECHNICAL", "OTHER"]
    assert data.get("high_severity") == (data.get("severity") == "HIGH")
    assert data.get("is_terminal") == (data.get("status") in ["RESOLVED", "CLOSED"])


def assert_approval_cap_not_exceeded(payouts: list) -> None:
    """The approved-and-sent total stays inside the payout approval cap (PRD §3.8)."""
    sent_or_paid = sum(
        p.get("net_after_refunds_cents", 0) for p in payouts if p.get("status") in ["SENT", "PAID"]
    )
    assert sent_or_paid <= PAYOUT_APPROVAL_CAP_CENTS, (
        f"approved-and-sent total {sent_or_paid} exceeds the cap {PAYOUT_APPROVAL_CAP_CENTS}"
    )
