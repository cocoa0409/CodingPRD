"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

APPLICATION_STATUSES = [
    "SUBMITTED",
    "UNDER_REVIEW",
    "SCHOOL_CERT_PENDING",
    "APPROVED",
    "DENIED",
    "CANCELLED",
    "DISBURSED",
    "CLOSED",
]
CERTIFICATION_STATUSES = [
    "REQUESTED",
    "CERTIFIED",
    "PARTIAL_CERTIFIED",
    "REJECTED",
    "EXPIRED",
]
LOAN_STATUSES = [
    "APPROVED",
    "IN_SCHOOL",
    "GRACE",
    "REPAYMENT",
    "FORBEARANCE_DEFERMENT",
    "DELINQUENT",
    "DEFAULT",
    "PAID_IN_FULL",
]
DISBURSEMENT_STATUSES = ["SCHEDULED", "RELEASED", "CANCELLED", "FAILED"]
PLAN_STATUSES = ["PENDING_APPROVAL", "ACTIVE", "SUPERSEDED", "DECLINED"]
PAYMENT_STATUSES = ["SCHEDULED", "PAID_ON_TIME", "PAID_LATE", "MISSED", "REVERSED"]
RELIEF_STATUSES = ["REQUESTED", "GRANTED", "DENIED", "CANCELLED"]
RELEASE_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DECLINED", "WITHDRAWN"]
DELINQUENCY_STAGES = ["CURRENT", "LATE", "DELINQUENT", "DEFAULT_ELIGIBLE"]


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_borrower(data: dict):
    _assert_common(data, "Borrower")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert len(data["state_code"]) == 2
    assert data["program_level"] in ("UNDERGRADUATE", "GRADUATE")
    assert data["status"] in ("ACTIVE", "LOCKED")
    assert data["enrollment_status"] in (
        "IN_SCHOOL",
        "LESS_THAN_HALF_TIME",
        "GRADUATED",
        "WITHDRAWN",
    )
    assert isinstance(data["on_time_payment_run_count"], int)
    assert isinstance(data["lifetime_on_time_payment_count"], int)


def assert_cosigner(data: dict):
    _assert_common(data, "Cosigner")
    assert data["underwriting_status"] in (
        "INVITED",
        "UNDER_REVIEW",
        "ELIGIBLE",
        "INELIGIBLE",
        "RELEASED",
    )


def assert_school(data: dict):
    _assert_common(data, "School")
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert isinstance(data["active"], bool)


def assert_policy(data: dict):
    _assert_common(data, "LoanPolicy")
    assert data["program_level"] in ("UNDERGRADUATE", "GRADUATE")


def assert_application(data: dict):
    _assert_common(data, "LoanApplication")
    assert data["application_status"] in APPLICATION_STATUSES


def assert_certification(data: dict):
    _assert_common(data, "SchoolCertification")
    assert data["certification_status"] in CERTIFICATION_STATUSES


def assert_loan(data: dict):
    _assert_common(data, "Loan")
    assert data["loan_status"] in LOAN_STATUSES
    assert data["delinquency_stage"] in DELINQUENCY_STAGES


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert data["disbursement_status"] in DISBURSEMENT_STATUSES


def assert_accrual_entry(data: dict):
    """The interest ledger row is append-only: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "InterestAccrualEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "InterestAccrualEntry.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "append-only ledger rows expose no updated_at"
    assert "version" not in data, "append-only ledger rows expose no version"
    assert data["entry_status"] in ("ACCRUED", "CAPITALIZED", "UNPAID_DUE", "WRITTEN_OFF")
    assert data["source_event"] in ("PERIOD_ACCRUAL", "CAPITALIZATION", "PAYMENT_REVERSAL")


def assert_repayment_plan(data: dict):
    _assert_common(data, "RepaymentPlan")
    assert data["plan_status"] in PLAN_STATUSES


def assert_payment(data: dict):
    _assert_common(data, "Payment")
    assert data["payment_status"] in PAYMENT_STATUSES


def assert_forbearance(data: dict):
    _assert_common(data, "ForbearanceDeferment")
    assert data["relief_status"] in RELIEF_STATUSES


def assert_release_application(data: dict):
    _assert_common(data, "CosignerReleaseApplication")
    assert data["release_status"] in RELEASE_STATUSES


def assert_loan_invariants(data: dict):
    """Balance identities that must hold after any loan-side operation."""
    assert data["disbursed_amount_cents"] >= 0
    assert data["current_balance_cents"] >= 0
    assert data["principal_cents"] >= 0


def assert_capitalized_within_cap(loan: dict):
    """Interest capitalized at repayment entry never exceeds the ten-percent cap."""
    assert loan["lifetime_capitalized_interest_cents"] >= 0
    assert (
        loan["lifetime_capitalized_interest_cents"]
        <= loan["max_allowed_capitalization_cents"]
    ), "capitalized interest may not exceed max_allowed_capitalization_cents"


def assert_headroom_non_negative(headroom_cents: int):
    assert headroom_cents >= 0, "certification headroom is floored at zero"


def assert_rate_is_margin_or_reduced(effective_rate_pct: float, margin_rate_pct: float):
    """effective_rate_pct is the margin, or the margin less the 0.25 reduction."""
    assert effective_rate_pct in (margin_rate_pct, round(margin_rate_pct - 0.25, 4)), (
        f"effective rate {effective_rate_pct} is neither margin {margin_rate_pct} "
        f"nor margin less 0.25"
    )