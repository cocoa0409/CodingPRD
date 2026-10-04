"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BORROWER_STATUSES = ["REGISTERED", "RESTRICTED"]
UNDERWRITING_VARIANTS = ["NONE", "STANDARD", "TRUSTEE_AUGMENTED"]
INVITE_STATUSES = ["SENT", "ACCEPTED", "DECLINED", "EXPIRED"]
TRUSTEE_STATUSES = ["ACTIVE", "SUSPENDED"]
SUSPENSION_REASONS = ["NONE", "MANUAL", "DEFAULT_RATE"]
APPLICATION_STATUSES = [
    "DRAFT",
    "IN_REVIEW",
    "APPROVED_PENDING_FUNDRAISE",
    "PRIVATE_FUNDRAISING",
    "PUBLIC_FUNDRAISING",
    "FUNDED",
    "WITHDRAWN",
    "EXPIRED_PRIVATE",
    "EXPIRED_PUBLIC",
    "REJECTED",
    "CANCELLED",
]
ENDORSEMENT_MODES = ["SELF_ENDORSED", "TRUSTEE_VOUCHED"]
ENDORSEMENT_STATUSES = ["ACTIVE", "CANCELLED", "REFUNDED", "CONVERTED"]
CONTRIBUTION_STATUSES = ["ACTIVE", "REFUNDED", "CONVERTED"]
LOAN_STATUSES = ["REPAYING", "DELINQUENT", "PAID_OFF", "DEFAULTED"]
SCHEDULE_STATUSES = ["PROVISIONAL", "FINAL"]
INSTALLMENT_STATUSES = ["PENDING", "DUE", "PARTIAL", "PAID", "LATE"]


def _assert_common(data: dict, entity: str, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(
            data.get("version"), int
        ), f"{entity}.version must be an integer"


def assert_borrower(data: dict):
    _assert_common(data, "Borrower")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["business_tenure_months"], int)
    assert isinstance(data["prior_repaid_loans_count"], int)
    assert data["status"] in BORROWER_STATUSES
    assert isinstance(data["social_underwriting_score"], (int, float))
    assert data["underwriting_variant"] in UNDERWRITING_VARIANTS
    assert isinstance(data["completed_loan_count"], int)
    assert isinstance(data["defaulted_loan_count"], int)


def assert_invite(data: dict):
    _assert_common(data, "UnderwritingInvite", versioned=False)
    assert "version" not in data, "UnderwritingInvite must not carry version"
    assert "updated_at" not in data, "UnderwritingInvite must not carry updated_at"
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["invitee_email"], str) and "@" in data["invitee_email"]
    assert isinstance(data["invite_token"], str) and data["invite_token"]
    assert data["status"] in INVITE_STATUSES


def assert_lender(data: dict):
    _assert_common(data, "Lender")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    for field in (
        "lending_balance_cents",
        "total_deposited_cents",
        "lifetime_lent_cents",
        "lifetime_repaid_cents",
    ):
        assert isinstance(data[field], int), f"Lender.{field} must be integer cents"
        assert data[field] >= 0, f"Lender.{field} must be non-negative"


def assert_trustee(data: dict):
    _assert_common(data, "Trustee")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["endorsement_limit_cents"], int)
    assert data["status"] in TRUSTEE_STATUSES
    assert data["suspension_reason"] in SUSPENSION_REASONS
    for field in (
        "active_endorsement_exposure_cents",
        "endorsed_terminal_count",
        "endorsed_defaulted_count",
        "default_rate_bps",
    ):
        assert isinstance(data[field], int), f"Trustee.{field} must be an integer"
    assert data["endorsed_defaulted_count"] <= data["endorsed_terminal_count"]


def assert_application(data: dict):
    _assert_common(data, "LoanApplication")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] > 0
    assert data["requested_amount_cents"] % 100 == 0
    assert isinstance(data["term_months"], int) and 3 <= data["term_months"] <= 36
    assert isinstance(data["business_purpose"], str)
    assert data["status"] in APPLICATION_STATUSES
    for field in (
        "distinct_endorser_count",
        "private_total_cents",
        "public_total_cents",
        "funded_total_cents",
    ):
        assert isinstance(data[field], int), f"LoanApplication.{field} must be int"
        assert data[field] >= 0
    assert (
        data["funded_total_cents"]
        == data["private_total_cents"] + data["public_total_cents"]
    ), "funded_total_cents must equal private + public totals"


def assert_endorsement(data: dict):
    _assert_common(data, "Endorsement")
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 2500
    assert isinstance(data["is_trustee_endorsement"], bool)
    assert data["status"] in ENDORSEMENT_STATUSES


def assert_contribution(data: dict):
    _assert_common(data, "Contribution")
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert is_valid_uuid(data.get("lender_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 2500
    assert data["status"] in CONTRIBUTION_STATUSES


def assert_loan(data: dict):
    _assert_common(data, "Loan")
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["term_months"], int)
    assert is_iso8601_timestamp(data.get("disbursed_at", ""))
    assert data["status"] in LOAN_STATUSES
    assert data["schedule_status"] in SCHEDULE_STATUSES
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0


def assert_installment(data: dict):
    _assert_common(data, "Installment")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert isinstance(data["installment_number"], int) and data["installment_number"] >= 1
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert data["status"] in INSTALLMENT_STATUSES


def assert_payment(data: dict):
    _assert_common(data, "Payment", versioned=False)
    assert "version" not in data, "Payment must not carry version"
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert is_valid_uuid(data.get("loan_id", ""))
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 100
    assert is_iso8601_timestamp(data.get("paid_at", ""))


def assert_impact_report(data: dict):
    _assert_common(data, "ImpactReport")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["months_after_disbursement"], int)
    assert isinstance(data["revenue_change_pct"], int)
    assert -100 <= data["revenue_change_pct"] <= 1000
    assert isinstance(data["jobs_created"], int) and 0 <= data["jobs_created"] <= 100
    assert isinstance(data["narrative"], str)
    assert isinstance(data["is_mid_term"], bool)


def assert_loan_invariants(loan: dict, installments: list):
    """Loan-level invariants that must hold after any repayment operation."""
    assert (
        loan["outstanding_cents"] == sum(i["remaining_cents"] for i in installments)
    ), "outstanding_cents must equal the sum of installment remaining_cents"
    if loan["status"] == "PAID_OFF":
        assert loan["outstanding_cents"] == 0, "PAID_OFF loans owe nothing"
