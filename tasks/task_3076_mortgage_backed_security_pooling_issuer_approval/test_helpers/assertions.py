"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_issuer_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("net_worth_cents"), int)
    assert isinstance(data.get("liquid_assets_cents"), int)
    assert isinstance(data.get("origination_experience_months"), int)
    assert isinstance(data.get("branch_count"), int)
    assert isinstance(data.get("annual_origination_volume_cents"), int)
    assert isinstance(data.get("net_worth_requirement_cents"), int)
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "UNDER_REVIEW",
        "REVISION_REQUESTED", "APPROVED", "DENIED",
    }
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_issuer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("net_worth_cents"), int)
    assert isinstance(data.get("liquid_assets_cents"), int)
    assert isinstance(data.get("advance_obligation_cents"), int)
    assert data.get("status") in {"ACTIVE", "WATCH", "SUSPENDED", "DEFAULTED", "EXTINGUISHED"}
    ratio_ex = data.get("liquidity_ratio_excluding_credit_bps")
    ratio_in = data.get("liquidity_ratio_including_credit_bps")
    if data["advance_obligation_cents"] == 0:
        assert ratio_ex is None, "excluding ratio must be null when obligation is zero"
        assert ratio_in is None, "including ratio must be null when obligation is zero"
    else:
        assert isinstance(ratio_ex, int)
        assert isinstance(ratio_in, int)
    assert isinstance(data.get("version"), int)


def assert_custodian(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("firm_name"), str) and data["firm_name"]


def assert_engagement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("custodian_id"), str)
    assert isinstance(data.get("issuer_id"), str)
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("window_end"), str)
    assert data.get("status") in {"ACTIVE", "ENDED"}


def assert_pool(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("issuer_id"), str)
    assert isinstance(data.get("custodian_id"), str)
    assert data.get("pool_type") in {"SINGLE_FAMILY", "MANUFACTURED_HOME", "MULTIFAMILY"}
    assert isinstance(data.get("term_months"), int)
    assert isinstance(data.get("note_rate_bps"), int)
    assert isinstance(data.get("aggregate_principal_cents"), int)
    assert isinstance(data.get("delinquency_rate_bps"), int)
    assert data.get("status") in {
        "DRAFT", "ASSEMBLED", "CERTIFIED", "LIVE", "TRANSFER_PENDING", "TERMINATED",
    }
    assert isinstance(data.get("version"), int)


def assert_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("pool_id"), str)
    assert isinstance(data.get("principal_balance_cents"), int)
    assert isinstance(data.get("note_rate_bps"), int)
    assert data.get("government_insurance") in {"FHA", "VA", "USDA", "PIH"}
    assert isinstance(data.get("escrow_monthly_cents"), int)
    assert data.get("status") in {
        "CURRENT", "DELINQ_30", "DELINQ_60", "DELINQ_90_PLUS", "FORECLOSURE", "PAID_OFF",
    }


def assert_custodial_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("issuer_id"), str)
    assert data.get("account_type") in {"P_AND_I", "T_AND_I"}
    assert isinstance(data.get("balance_cents"), int)
    assert data.get("status") in {"ACTIVE", "FROZEN", "CLOSED"}


def assert_account_transaction(data: dict):
    """Append-only ledger entry: carries id + created_at only — never
    updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert data.get("direction") in {"DEPOSIT", "DISBURSEMENT"}
    assert data.get("component") in {"PRINCIPAL", "INTEREST", "TAX", "INSURANCE", "ESCROW"}
    assert isinstance(data.get("amount_cents"), int)


def assert_investor_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("pool_id"), str)
    assert isinstance(data.get("period_month"), str)
    assert isinstance(data.get("scheduled_payment_cents"), int)
    assert isinstance(data.get("actual_collected_cents"), int)
    assert isinstance(data.get("advance_required_cents"), int)
    assert data.get("status") in {"DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_pass_through_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("report_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in {"DUE", "PAID", "ADVANCED"}
    fs = data.get("funding_source")
    assert fs is None or fs in {"CUSTODIAL", "ADVANCE"}


def assert_liquidity_advance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("issuer_id"), str)
    assert isinstance(data.get("payment_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in {"OPEN", "REIMBURSED", "WRITTEN_OFF"}


def assert_delinquency_breach(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("issuer_id"), str)
    assert isinstance(data.get("pool_id"), str)
    assert isinstance(data.get("delinquency_rate_bps_at_breach"), int)
    assert data.get("status") in {"OPEN", "MITIGATING", "CLOSED"}


def assert_corrective_action_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("breach_id"), str)
    assert isinstance(data.get("plan_summary"), str)
    assert isinstance(data.get("target_cure_month"), str)
    assert data.get("status") in {"SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_portfolio_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("defaulted_issuer_id"), str)
    assert isinstance(data.get("successor_issuer_id"), str)
    assert data.get("status") in {"INITIATED", "ACCEPTED", "REJECTED", "COMPLETED"}


def assert_custodial_reconciliation(account: dict):
    """PRD §2.10 ledger invariant: balance equals the sum of the account's
    two component balances for its type."""
    if account["account_type"] == "P_AND_I":
        assert (
            account["balance_cents"]
            == account["principal_balance_cents"] + account["interest_balance_cents"]
        ), "P_AND_I balance must equal principal + interest components"
    else:
        assert (
            account["balance_cents"]
            == account["tax_balance_cents"] + account["insurance_balance_cents"]
        ), "T_AND_I balance must equal tax + insurance components"
