"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the common properties of PRD §2.5 plus the
entity's own field types and enum ranges. Invariant checkers encode PRD
arithmetic that must hold on any response carrying those fields.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DUES_BASE_CENTS,
    GRADE_NAMES,
    QUARTERLY_INSTALLMENT_COUNT,
    SIZE_TIERS,
    expected_grade,
)
from .types import (
    OPEN_COMPLAINT_STATES,
    CLOSED_COMPLAINT_STATES,
)


# ---------------------------------------------------------------------------
# Common-property helper (PRD §2.5)
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1"


def _assert_nullable_ts(data: dict, field: str, entity: str):
    value = data.get(field, "missing")
    assert value is None or is_iso8601_timestamp(value), \
        f"{entity}.{field} must be null or ISO 8601, got {value!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_bureau(data: dict):
    _assert_common_fields(data, "Bureau")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["territory_state_codes"], list)
    assert all(isinstance(s, str) and len(s) == 2
               for s in data["territory_state_codes"])
    assert isinstance(data["local_dues_fee_cents"], int)
    assert data["local_dues_fee_cents"] >= 0
    assert isinstance(data["dues_collected_cents"], int)
    assert isinstance(data["ops_day_index"], int)
    assert data["ops_day_index"] >= 0


def assert_consumer(data: dict):
    _assert_common_fields(data, "Consumer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["home_state_code"], str)
    assert len(data["home_state_code"]) == 2
    assert isinstance(data["complaints_filed_count"], int)
    assert data["complaints_filed_count"] >= 0


def assert_business(data: dict):
    _assert_common_fields(data, "Business")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["employee_count"], int)
    assert data["employee_count"] >= 1, "PRD §3.1: employee_count at least 1"
    assert is_iso8601_timestamp(data["founded_on"])
    assert is_valid_uuid(data.get("bureau_id", "")), \
        "Business.bureau_id must reference a bureau"
    assert data["size_tier"] in SIZE_TIERS
    assert data["accreditation_status"] in (
        "NOT_ACCREDITED", "ACCREDITED", "SUSPENDED", "REVOKED")
    assert data["advertising_compliance_status"] in (
        "CLEAR", "UNDER_AD_REVIEW", "REFERRED_TO_REGULATOR")
    for counter in ("suspension_count_24m", "complaints_received_36m",
                    "complaints_unanswered_36m", "complaints_unresolved_36m",
                    "complaints_open_count", "complaints_closed_count",
                    "published_scam_count_12m"):
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"Business.{counter} must be a non-negative integer"
    _assert_nullable_ts(data, "last_suspension_at", "Business")
    for field in ("current_published_score", "current_provisional_score"):
        value = data.get(field, "missing")
        assert value is None or isinstance(value, int), \
            f"Business.{field} must be null or int"
    for field in ("current_published_grade", "current_provisional_grade"):
        value = data.get(field, "missing")
        assert value is None or value in GRADE_NAMES, \
            f"Business.{field} must be null or a grade"


def assert_accreditation_application(data: dict):
    _assert_common_fields(data, "AccreditationApplication")
    assert is_valid_uuid(data.get("business_id", ""))
    assert data["billing_plan"] in ("ANNUAL_PREPAID", "QUARTERLY")
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED_PENDING_DUES", "ACCREDITED",
        "DENIED", "EXPIRED")
    assert isinstance(data["reapplication_count"], int)
    assert data["reapplication_count"] >= 0
    _assert_nullable_ts(data, "submitted_at", "AccreditationApplication")
    _assert_nullable_ts(data, "decided_at", "AccreditationApplication")
    for field in ("denial_reason", "dues_invoice_id"):
        assert field in data, f"AccreditationApplication.{field} missing"
    for field in ("advertising_practices_result", "complaint_history_result",
                  "licensing_result"):
        value = data.get(field, "missing")
        assert value is None or value in ("PASS", "FAIL"), \
            f"AccreditationApplication.{field} must be null, PASS, or FAIL"


def assert_dues_invoice(data: dict):
    _assert_common_fields(data, "DuesInvoice")
    assert is_valid_uuid(data.get("business_id", ""))
    assert data["billing_plan"] in ("ANNUAL_PREPAID", "QUARTERLY")
    assert data["size_tier_at_issue"] in SIZE_TIERS
    assert data["base_amount_cents"] == DUES_BASE_CENTS[
        data["size_tier_at_issue"]], \
        "DuesInvoice.base_amount_cents must be the tier base dues (PRD §3.3)"
    assert isinstance(data["local_fee_cents"], int)
    assert data["local_fee_cents"] >= 0
    for field in ("amount_due_cents", "paid_cents", "refunded_cents",
                  "balance_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"DuesInvoice.{field} must be a non-negative integer"
    assert data["status"] in (
        "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "REFUNDED", "VOID")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["due_date"])
    _assert_nullable_ts(data, "voided_at", "DuesInvoice")
    assert_invoice_balance_invariant(data)
    assert_invoice_installments(data)


def assert_invoice_balance_invariant(data: dict):
    """PRD §3.3: balance_cents == amount_due_cents - (paid - refunded),
    never negative."""
    net = data["paid_cents"] - data["refunded_cents"]
    expected = data["amount_due_cents"] - net
    assert data["balance_cents"] == expected, (
        f"balance_cents {data['balance_cents']} != amount_due "
        f"{data['amount_due_cents']} - net {net}")
    assert data["balance_cents"] >= 0


def assert_invoice_installments(data: dict):
    """PRD §3.3: ANNUAL_PREPAID holds one installment; QUARTERLY holds four
    whose amounts sum to amount_due_cents."""
    installments = data["installments"]
    assert isinstance(installments, list) and installments
    if data["billing_plan"] == "ANNUAL_PREPAID":
        assert len(installments) == 1
        assert installments[0]["installment"] == 1
        assert installments[0]["amount_cents"] == data["amount_due_cents"]
    else:
        assert len(installments) == QUARTERLY_INSTALLMENT_COUNT
        assert [i["installment"] for i in installments] == [1, 2, 3, 4]
        assert sum(i["amount_cents"] for i in installments) == \
            data["amount_due_cents"], "installments must sum to amount_due"


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert is_valid_uuid(data.get("business_id", ""))
    assert data["category"] in (
        "SERVICE", "PRODUCT", "BILLING", "ADVERTISING", "DELIVERY",
        "WARRANTY", "OTHER")
    assert isinstance(data["description"], str)
    assert data["status"] in OPEN_COMPLAINT_STATES + CLOSED_COMPLAINT_STATES
    assert is_iso8601_timestamp(data["filed_at"])
    _assert_nullable_ts(data, "forwarded_at", "Complaint")
    _assert_nullable_ts(data, "response_deadline_at", "Complaint")
    _assert_nullable_ts(data, "last_unresolved_at", "Complaint")
    _assert_nullable_ts(data, "closed_at", "Complaint")
    outcome = data.get("resolution_outcome", "missing")
    assert outcome is None or outcome in (
        "CONSUMER_ACCEPTED", "CONSUMER_REJECTED", "AUTO_UNANSWERED",
        "MEDIATION_AGREEMENT", "MEDIATION_NO_AGREEMENT",
        "ARBITRATION_ADVERSE", "ARBITRATION_NO_FAULT")
    assert isinstance(data["rebuttal_count"], int)
    assert 0 <= data["rebuttal_count"] <= 3, \
        "PRD §3.4: a complaint admits at most 3 consumer rebuttals"
    assert isinstance(data["reopen_count"], int)
    assert data["reopen_count"] >= 0
    assert isinstance(data["responses"], list)
    for entry in data["responses"]:
        assert entry["kind"] in (
            "BUSINESS_RESPONSE", "CONSUMER_REBUTTAL", "CONSUMER_ACCEPT",
            "CONSUMER_REJECT")
        assert isinstance(entry["body"], str)
        assert is_iso8601_timestamp(entry["received_at"])
        assert isinstance(entry["on_time"], bool)


def assert_mediation_case(data: dict):
    _assert_common_fields(data, "MediationCase")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "DECLINED", "DECLINED_EXPIRED", "SCHEDULED",
        "CONCLUDED_AGREEMENT", "CONCLUDED_NO_AGREEMENT")
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["offer_deadline_at"])
    for field in ("business_response", "consumer_response"):
        assert data[field] in ("PENDING", "ACCEPTED", "DECLINED"), \
            f"MediationCase.{field} must be PENDING, ACCEPTED, or DECLINED"
    _assert_nullable_ts(data, "session_start_at", "MediationCase")
    _assert_nullable_ts(data, "session_end_at", "MediationCase")


def assert_arbitration_case(data: dict):
    _assert_common_fields(data, "ArbitrationCase")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["status"] in ("FILED", "HEARING_SCHEDULED", "DECIDED")
    _assert_nullable_ts(data, "hearing_start_at", "ArbitrationCase")
    _assert_nullable_ts(data, "hearing_end_at", "ArbitrationCase")
    _assert_nullable_ts(data, "decided_at", "ArbitrationCase")
    outcome = data.get("outcome", "missing")
    assert outcome is None or outcome in ("ADVERSE_TO_BUSINESS", "NO_FAULT")


def assert_rating_snapshot(data: dict):
    _assert_common_fields(data, "RatingSnapshot")
    assert is_valid_uuid(data.get("business_id", ""))
    assert data["variant"] in ("PROVISIONAL", "PUBLISHED")
    for component in ("volume_deduction", "unanswered_deduction",
                      "unresolved_deduction", "arbitration_deduction",
                      "age_deduction", "advertising_deduction",
                      "scam_deduction", "pending_deduction",
                      "total_deductions"):
        assert isinstance(data[component], int) and data[component] >= 0, \
            f"RatingSnapshot.{component} must be a non-negative integer"
    assert isinstance(data["score"], int)
    assert 0 <= data["score"] <= 100, \
        "PRD §3.6: score is 100 minus total deductions, floored at 0"
    assert data["grade"] in GRADE_NAMES
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["computed_at"])
    _assert_nullable_ts(data, "published_at", "RatingSnapshot")
    assert_snapshot_arithmetic(data)


def assert_snapshot_arithmetic(data: dict):
    """PRD §3.6: total_deductions is the sum of the eight components, the
    score is 100 minus the sum floored at 0, and the grade matches the
    score's inclusive-lower-bound band."""
    components = (
        "volume_deduction", "unanswered_deduction", "unresolved_deduction",
        "arbitration_deduction", "age_deduction", "advertising_deduction",
        "scam_deduction", "pending_deduction",
    )
    total = sum(data[c] for c in components)
    assert data["total_deductions"] == total, (
        f"total_deductions {data['total_deductions']} != sum of components "
        f"{total}")
    assert data["score"] == max(0, 100 - total)
    assert data["grade"] == expected_grade(data["score"]), (
        f"grade {data['grade']} inconsistent with score {data['score']}")


def assert_rating_dispute(data: dict):
    _assert_common_fields(data, "RatingDispute")
    assert is_valid_uuid(data.get("business_id", ""))
    assert is_valid_uuid(data.get("snapshot_id", ""))
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in (
        "FILED", "UNDER_APPEAL_REVIEW", "UPHELD", "OVERRULED")
    assert is_iso8601_timestamp(data["filed_at"])


def assert_advertising_review(data: dict):
    _assert_common_fields(data, "AdvertisingReview")
    assert is_valid_uuid(data.get("business_id", ""))
    assert isinstance(data["claim_description"], str)
    assert data["claim_description"]
    assert data["status"] in (
        "UNDER_REVIEW", "CLEARED", "REFERRED_TO_REGULATOR")
    assert is_iso8601_timestamp(data["opened_at"])
    _assert_nullable_ts(data, "concluded_at", "AdvertisingReview")
    _assert_nullable_ts(data, "referred_at", "AdvertisingReview")


def assert_scam_report(data: dict):
    _assert_common_fields(data, "ScamReport")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert is_valid_uuid(data.get("business_id", ""))
    assert isinstance(data["description"], str) and data["description"]
    assert is_iso8601_timestamp(data["incident_date"])
    assert data["status"] in ("RECEIVED", "PUBLISHED")
    _assert_nullable_ts(data, "published_at", "ScamReport")


def assert_scam_pattern_row(data: dict):
    """PRD §3.8: one row of the computed scam-pattern publication."""
    assert is_valid_uuid(data.get("business_id", ""))
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["published_report_count_12m"], int)
    assert data["published_report_count_12m"] >= 1, \
        "PRD §3.8: every business with at least 1 such report appears"
    assert isinstance(data["pattern_flag"], bool)
