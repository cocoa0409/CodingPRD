"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BatchStatus,
    CatchUpStatus,
    DisclosureStatus,
    EnforcementStatus,
    GuarantorStatus,
    LoanStatus,
    MerchantStatus,
    OfferStatus,
    SaleStatus,
    SignalStatus,
    SweepStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_merchant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in [s.value for s in MerchantStatus]
    for field in ("lifetime_net_cents", "trailing_12m_months_recorded",
                  "trailing_30d_net_cents", "prior_30d_net_cents", "loans_repaid_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert "active_loan_id" in data


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["processing_date"], str)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["refunds_cents"], int)
    assert isinstance(data["chargebacks_cents"], int)
    assert data["net_settled_cents"] == (
        data["gross_cents"] - data["refunds_cents"] - data["chargebacks_cents"]
    ), "net_settled_cents must equal gross - refunds - chargebacks"
    assert data["status"] in [s.value for s in BatchStatus]


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["status"] in [s.value for s in OfferStatus]
    for field in ("preapproved_standard_cents", "preapproved_conservative_cents",
                  "preapproved_cents", "trailing_12m_avg_net_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["renewal_count"], int)


def assert_loan(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in LoanStatus]
    for field in ("principal_cents", "fee_cents", "total_repayment_cents",
                  "per_period_minimum_cents", "remaining_balance_cents",
                  "paid_to_date_cents", "repayment_period_index",
                  "consecutive_missed_periods", "carried_surplus_cents",
                  "cumulative_shortfall_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["disclosure_required"], bool)


def assert_loan_ledger_invariants(loan: dict):
    """Ledger conservation: total_repayment == remaining + paid, exactly."""
    assert loan["total_repayment_cents"] == (
        loan["remaining_balance_cents"] + loan["paid_to_date_cents"]
    ), (
        f"Ledger drift: total {loan['total_repayment_cents']} != "
        f"remaining {loan['remaining_balance_cents']} + paid {loan['paid_to_date_cents']}"
    )
    assert loan["remaining_balance_cents"] >= 0
    assert loan["paid_to_date_cents"] >= 0


def assert_guarantor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["status"] in [s.value for s in GuarantorStatus]
    assert isinstance(data["guarantee_cap_cents"], int)


def assert_disclosure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["status"] in [s.value for s in DisclosureStatus]
    assert isinstance(data["mandate_state"], bool)
    assert isinstance(data["cooling_required"], bool)
    assert data["disclosed_apr_basis"] in ("SCHEDULED", "PROJECTED")


def assert_sweep(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["batch_id"])
    assert isinstance(data["holdback_cents"], int)
    assert isinstance(data["clipped"], bool)
    assert data["status"] in [s.value for s in SweepStatus]


def assert_catch_up(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [s.value for s in CatchUpStatus]


def assert_enforcement_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["guarantor_id"])
    assert data["status"] in [s.value for s in EnforcementStatus]


def assert_bank(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["committed_exposure_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["bank_id"])
    assert isinstance(data["purchase_price_cents"], int)
    assert data["status"] in [s.value for s in SaleStatus]


def assert_migration_signal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["status"] in [s.value for s in SignalStatus]
    assert isinstance(data["volume_only_would_trigger"], bool)
    assert isinstance(data["triggered"], bool)


def assert_bank_exposure_invariant(bank: dict):
    assert bank["committed_exposure_cents"] >= 0, "committed exposure must never go negative"
