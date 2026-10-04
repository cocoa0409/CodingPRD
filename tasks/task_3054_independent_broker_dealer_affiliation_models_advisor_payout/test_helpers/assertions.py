"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_branch(data: dict):
    _assert_common(data, "Branch")
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["transmittal_account"], str) and data["transmittal_account"]
    assert isinstance(data["osj_name"], str)
    assert isinstance(data["osj_enabled"], bool)
    assert data["state"] in ("SUPERVISED", "UNSUPERVISED")
    assert data["status"] in ("DRAFT", "ACTIVE")
    assert isinstance(data["supervising_advisor_count"], int)
    assert data["supervising_advisor_count"] >= 0
    assert data["current_payout_period_id"] is None or \
        is_valid_uuid(data["current_payout_period_id"])


def assert_advisor(data: dict):
    _assert_common(data, "Advisor")
    assert isinstance(data["advisor_code"], str) and data["advisor_code"]
    assert isinstance(data["crd_number"], str)
    assert isinstance(data["full_name"], str)
    assert data["affiliation_model"] in ("IC", "EMPLOYEE", "HYBRID", "INSTITUTIONAL")
    assert isinstance(data["primary_branch_code"], str)
    assert isinstance(data["ingested_book_total_cents"], int)
    assert isinstance(data["book_transferred_cents"], int)
    assert isinstance(data["book_portability_pct"], int)
    assert isinstance(data["protocol_eligible"], bool)
    assert isinstance(data["outstanding_loan_balance_cents"], int)
    assert data["eo_coverage_level"] in ("STANDARD", "PREMIUM", "LIMITED")
    assert isinstance(data["annual_payout_cap_hit"], bool)
    assert data["retention_status"] in (
        "NOT_AT_RISK", "CONTESTED", "RETAINED", "DEPARTED_CONFIRMED")
    assert data["status"] in (
        "PROSPECT", "ONBOARDING", "ACTIVE", "SUSPENDED", "DEPARTING", "DEPARTED")


def assert_supervisor_enrollment(data: dict):
    _assert_common(data, "BranchSupervisorEnrollment")
    assert isinstance(data["branch_code"], str)
    assert isinstance(data["advisor_code"], str)
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("REQUESTED", "ENROLLED", "REVOKED")


def assert_advisor_link(data: dict):
    _assert_common(data, "AdvisorBranchLink")
    assert isinstance(data["advisor_code"], str)
    assert isinstance(data["branch_code"], str)
    assert isinstance(data["is_supervisor"], bool)
    assert data["assignment_type"] in ("PRIMARY", "SECONDARY")
    assert data["status"] in ("ASSIGNED", "INACTIVE")


def assert_account(data: dict):
    _assert_common(data, "Account")
    assert isinstance(data["advisor_code"], str)
    assert isinstance(data["account_number"], str)
    assert data["account_type"] in ("ADVISORY", "BROKERAGE")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["held_away"], bool)
    assert isinstance(data["fee_levelized"], bool)
    assert data["status"] in (
        "OPEN", "FROZEN", "PENDING_TRANSFER", "TRANSFERRED_OUT",
        "RETENTION_CONTESTED", "RETAINED")


def assert_revenue_entry(data: dict):
    _assert_common(data, "RevenueEntry")
    assert isinstance(data["advisor_code"], str)
    assert is_valid_uuid(data["account_id"])
    assert data["product_type"] in (
        "EQUITY", "MUTUAL_FUND", "ANNUITY", "BROKERAGE_TRAIL", "ADVISORY")
    assert isinstance(data["gross_commission_cents"], int)
    assert data["gross_commission_cents"] > 0
    assert isinstance(data["production_date"], str)
    assert data["status"] in ("DRAFT", "RELEASED", "TRUE_UP_APPLIED", "VOID")


def assert_payout_period(data: dict):
    _assert_common(data, "PayoutPeriod")
    assert isinstance(data["branch_code"], str)
    assert isinstance(data["year"], int)
    assert 1 <= data["month"] <= 12
    assert 1 <= data["period_index"] <= 5
    assert data["state"] in ("OPEN", "CLOSED", "PAID", "REOPENED", "VOID")
    assert data["status"] in ("OPEN", "CLOSED", "PAID", "REOPENED", "VOID")
    assert isinstance(data["period_gross_cents"], int)
    assert isinstance(data["period_payout_cents"], int)
    assert isinstance(data["true_up_amount_cents"], int)


def assert_payout_line(data: dict):
    _assert_common(data, "AdvisorPayoutLine")
    assert is_valid_uuid(data["payout_period_id"])
    assert isinstance(data["advisor_code"], str)
    assert isinstance(data["period_gross_cents"], int)
    assert isinstance(data["projected_annual_production_cents"], int)
    assert isinstance(data["provisional_base_rate_bps"], int)
    assert isinstance(data["release_amount_cents"], int)
    assert isinstance(data["true_up_amount_cents"], int)
    assert data["status"] in ("DRAFT", "RELEASED", "TRUE_UP_APPLIED", "VOID")


def assert_payout_loan(data: dict):
    _assert_common(data, "PayoutLoan")
    assert isinstance(data["advisor_code"], str)
    assert isinstance(data["principal_cents"], int)
    assert 0 < data["principal_cents"] <= 50_000_000
    assert isinstance(data["amortization_rate_bps"], int) and data["amortization_rate_bps"] > 0
    assert 0 <= data["forgiveness_milestone_pct"] <= 100
    assert isinstance(data["remaining_balance_cents"], int)
    assert data["remaining_balance_cents"] >= 0
    assert isinstance(data["milestone_progress_cents"], int)
    assert data["status"] in (
        "REQUESTED", "ACTIVE", "AMORTIZING", "REPAID", "FORGIVEN", "DISCHARGED")


def assert_amortization_entry(data: dict):
    _assert_common(data, "LoanAmortizationEntry")
    assert is_valid_uuid(data["payout_loan_id"])
    assert is_valid_uuid(data["payout_period_id"])
    assert isinstance(data["amortization_amount_cents"], int)
    assert isinstance(data["forgiveness_amount_cents"], int)
    assert data["status"] in ("POSTED", "VOID")


def assert_expense_pass_through(data: dict):
    _assert_common(data, "ExpensePassThrough")
    assert isinstance(data["advisor_code"], str)
    assert is_valid_uuid(data["payout_period_id"])
    assert data["category"] in ("TECHNOLOGY", "CLEARING", "E_AND_O", "REGULATORY")
    assert data["billing_model"] in ("FLAT_MONTHLY", "PCT_OF_GROSS")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "POSTED", "WAIVED")


def assert_advisory_split(data: dict):
    _assert_common(data, "AdvisoryRevenueSplit")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["payout_period_id"])
    assert isinstance(data["advisory_fee_cents"], int)
    assert isinstance(data["brokerage_revenue_cents"], int)
    assert isinstance(data["advisory_revenue_cents"], int)
    assert isinstance(data["levelization_delta_cents"], int)
    assert data["status"] in ("PENDING", "POSTED", "VOID")


def assert_transition(data: dict):
    _assert_common(data, "TransitionRecord")
    assert isinstance(data["advisor_code"], str)
    assert is_valid_uuid(data["payout_period_id"])
    assert isinstance(data["accounts_in_contest_count"], int)
    assert isinstance(data["accounts_retained_count"], int)
    assert isinstance(data["settled_amount_cents"], int)
    assert isinstance(data["retention_ratio_bps"], int)
    assert data["status"] in ("PENDING", "CONTESTED", "SETTLED")


def assert_account_retention(data: dict):
    _assert_common(data, "AccountRetention")
    assert is_valid_uuid(data["transition_record_id"])
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["retention_rate_bps"], int) and data["retention_rate_bps"] > 0
    assert isinstance(data["credit_amount_cents"], int)
    assert data["status"] in ("PENDING", "POSTED", "RETAINED", "LOST", "VOID")


# ─── Domain invariants ────────────────────────────────

def assert_loan_conservation_identity(loan: dict):
    """principal == remaining + posted amortization + posted forgiveness."""
    assert loan["remaining_balance_cents"] >= 0
    assert loan["remaining_balance_cents"] <= loan["principal_cents"]


def assert_grid_rate_in_band(rate_bps: int):
    assert 500 <= rate_bps <= 9000, f"grid rate {rate_bps} outside the 500-9000 band"


def assert_net_settlement_floor(result: dict):
    """A settlement is never negative and the override never exceeds the net."""
    assert result["net_settlement_cents"] >= 0
    assert result["pass_through_cents"] >= 0
    assert result["eo_charge_cents"] >= 0
    assert result["supervisory_override_cents"] >= 0