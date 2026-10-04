"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_instant_equals(actual: str, expected_iso: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    PRD pins the instant (e.g. coverage_start 00:00:00Z + 5 days; request
    clock + 14 days) but not the fractional-digit rendering, so compare
    parsed instants rather than exact strings."""
    def _parse(s):
        t = s.strip()
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)

    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 timestamp"
    assert _parse(actual) == _parse(expected_iso), (
        f"{actual!r} and {expected_iso!r} are not the same instant"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_hospital(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["APPLIED", "APPROVED", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["running_ledger_balance_cents"], int)


def assert_rate_filing(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FILED", "EFFECTIVE", "SUPERSEDED"]
    assert data["species"] in ["DOG", "CAT"]
    assert isinstance(data["base_monthly_premium_cents"], int)
    assert isinstance(data["age_band_multipliers"], dict)


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["enrollment_status"] in ["INJURY_WAITING", "ILLNESS_WAITING", "FULLY_ACTIVE"]
    assert data["lifecycle_status"] in ["ACTIVE", "CANCELLED", "LAPSED"]
    assert data["species"] in ["DOG", "CAT"]
    assert isinstance(data["per_condition_deductible_cents"], int)
    assert 0 < data["reimbursement_rate"] <= 1
    assert isinstance(data["current_monthly_premium_cents"], int)
    assert isinstance(data["filed_base_cents"], int)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "PREEXISTING_REVIEW", "ADJUDICATED", "DENIED",
        "PAID", "PAYMENT_FAILED", "SETTLED", "REOPENED",
    ]
    assert data["claim_type"] in ["INJURY", "ILLNESS"]
    for field in ("total_invoice_cents", "eligible_cents", "deductible_applied_cents",
                  "reimbursement_cents", "member_responsibility_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_claim_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "claim line carries no updated_at"
    assert "version" not in data, "claim line carries no version"
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert data["category"] in ["TREATMENT", "EXAM_FEE", "TAX", "OTHER_EXCLUDED"]
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["DIRECT_PAY", "CLAWBACK"]
    assert data["status"] in ["INITIATED", "SETTLED", "FAILED", "REVERSED"]
    assert data["ledger_status"] in ["POSTED", "PENDING_POST", "EXCLUDED"]
    assert isinstance(data["amount_cents"], int)


def assert_medical_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "medical record carries no updated_at"
    assert "version" not in data, "medical record carries no version"
    assert data["record_type"] in ["EXAM", "LAB", "IMAGING", "PROCEDURE", "PRESCRIPTION"]


def assert_policy_condition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["preexisting"], bool)
    assert isinstance(data["deductible_target_cents"], int)
    assert isinstance(data["deductible_accumulated_cents"], int)
    assert isinstance(data["lifetime_reimbursed_cents"], int)
    assert 0 <= data["deductible_accumulated_cents"] <= data["deductible_target_cents"], (
        "accumulated deductible never exceeds its target"
    )


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "RECORDS_REQUESTED", "UNDER_REVIEW", "UPHELD", "OVERTURNED"]
    assert data["reason_code"] in [
        "PREEXISTING_DISPUTE", "CONDITION_DEFINITION", "COVERAGE_DENIAL", "LINE_CATEGORIZATION",
    ]


def assert_reconciliation_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "reconciliation report carries no updated_at"
    assert "version" not in data, "reconciliation report carries no version"
    assert data["status"] in ["GENERATED", "ACKNOWLEDGED", "DISPUTED"]
    for field in ("expected_cents", "actual_cents", "discrepancy_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_claim_totals_consistent(claim: dict):
    """Domain invariants that must hold after adjudication."""
    assert claim["member_responsibility_cents"] == (
        claim["total_invoice_cents"] - claim["reimbursement_cents"]
    ), "member responsibility = total invoice minus reimbursement"
    assert claim["reimbursement_cents"] >= 0
    assert claim["eligible_cents"] >= 0
    assert claim["deductible_applied_cents"] >= 0
