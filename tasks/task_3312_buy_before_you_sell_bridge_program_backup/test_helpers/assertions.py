"""Entity assertions and domain invariant checkers.

Every entity in this API carries id / created_at / updated_at / version
(PRD section 2.5), so the shared entity check validates all four.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp, assert_cost_precision


def assert_common_fields(data: dict):
    """Every entity carries a server-minted UUID id and the three common fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a plain server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_homeowner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["program_status"] in [
        "NONE", "QUALIFYING", "ENROLLED", "BRIDGED", "SETTLED", "WITHDRAWN",
    ]
    assert isinstance(data["sealed_flag"], bool)


def assert_property(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["DEPARTING", "NEW"]
    assert data["condition_grade"] in ["A", "B", "C", "D"]
    assert data["listing_status"] in [
        "UNLISTED", "LISTED", "UNDER_CONTRACT", "SOLD_TO_PROGRAM", "RESOLD",
    ]
    assert data["repair_status"] in ["NOT_STARTED", "IN_PROGRESS", "COMPLETE"]
    assert_cost_precision(data["appraised_value_cents"])
    assert data["mortgage_payoff_cents"] >= 0
    assert data["purchase_price_cents"] >= 0


def assert_qualification(data: dict):
    assert_common_fields(data)
    assert data["variant_used"] in ["CONSERVATIVE", "OPTIMISTIC"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "EXPIRED"]
    assert_cost_precision(data["capacity_cents"])
    assert data["capacity_cents"] >= 0
    assert isinstance(data["equity_ratio"], (int, float))


def assert_bridge_program(data: dict):
    assert_common_fields(data)
    assert data["advance_status"] in ["PENDING", "FUNDING", "FUNDED", "SETTLED"]
    assert data["occupancy_status"] in [
        "VACANT", "OCCUPYING_NEW", "DEPARTING_LISTED", "DEPARTING_SOLD",
    ]
    assert_cost_precision(data["outstanding_carrying_cost_cents"])
    assert data["outstanding_carrying_cost_cents"] >= 0
    assert data["projected_carry_months"] >= 1 and data["projected_carry_months"] <= 24


def assert_interim_loan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ORIGINATED", "DRAWN", "REPAYING", "REPAID", "DELINQUENT"]
    assert_cost_precision(data["principal_cents"])
    assert_cost_precision(data["outstanding_principal_cents"])
    assert data["outstanding_principal_cents"] >= 0, "outstanding principal is never negative"
    assert data["accrued_interest_cents"] >= 0, "accrued interest is never negative"
    assert data["drawn_cents"] >= 0


def assert_bridge_advance(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "APPROVED", "DISBURSED", "REPAID", "REJECTED"]
    assert data["purpose"] in [
        "DOWN_PAYMENT", "CARRYING_COST", "REPAIR", "FEE", "DISCLOSURE",
    ]
    assert_cost_precision(data["amount_cents"])
    assert data["amount_cents"] > 0, "an advance amount must be strictly greater than zero"


def assert_carrying_cost(data: dict):
    assert_common_fields(data)
    assert data["kind"] in [
        "DEPARTING_TAX", "DEPARTING_INSURANCE", "DEPARTING_HOA", "DEPARTING_UTILITY",
        "NEW_TAX", "NEW_INSURANCE", "NEW_HOA", "NEW_UTILITY",
    ]
    assert data["repayment_status"] in ["UNPAID", "REPAID"]
    assert_cost_precision(data["amount_cents"])


def assert_repair_advance(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "APPROVED", "DISBURSED", "SETTLED"]
    assert data["escrow_release_mode"] in ["LUMP_SUM", "MILESTONE"]
    assert_cost_precision(data["approved_amount_cents"])
    assert data["repaid_cents"] >= 0


def assert_backup_offer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ISSUED", "EXPIRED", "EXTENDED", "EXERCISED", "VOIDED"]
    assert_cost_precision(data["offer_price_cents"])
    assert data["window_days"] >= 1 and data["window_days"] <= 180
    assert_cost_precision(data["price_basis_cents"])


def assert_listing(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "LIVE", "PAUSED", "CLOSED"]
    assert data["marketing_status"] in ["NOT_STARTED", "ACTIVE", "STOPPED"]
    assert data["offer_count"] >= 0


def assert_agent(data: dict):
    assert_common_fields(data)
    assert data["qualification_status"] in ["PENDING", "QUALIFIED", "SUSPENDED"]
    assert data["active_referral_count"] >= 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["role_scope"] in ["DEPARTING_SIDE", "NEW_SIDE", "RESALE_SIDE"]
    assert data["status"] in ["OPEN", "COMPLETED", "VOIDED"]
    assert_cost_precision(data["base_fee_cents"])
    assert_cost_precision(data["reconciled_fee_cents"])
    assert data["fee_variance_cents"] == data["reconciled_fee_cents"] - data["base_fee_cents"], (
        "fee_variance_cents is reconciled minus base"
    )


def assert_coordination_task(data: dict):
    assert_common_fields(data)
    assert data["task_kind"] in [
        "PHOTOGRAPHY", "INSPECTION", "APPRAISAL", "REPAIR_BID", "CLOSING_PREP", "RESALE_PREP",
    ]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


def assert_disbursement(data: dict):
    assert_common_fields(data)
    assert data["source_kind"] in ["CLOSING_SALE", "RESALE", "REPAIR_CLAWBACK"]
    assert data["status"] in ["RECORDED", "APPLIED"]
    assert_cost_precision(data["amount_cents"])
    assert data["applied_to_principal_cents"] >= 0
    assert data["applied_to_interest_cents"] >= 0


def assert_program_invariants(data: dict):
    """Domain invariants that hold for a BridgeProgram after any operation."""
    assert data["outstanding_carrying_cost_cents"] >= 0
    assert_cost_precision(data["outstanding_carrying_cost_cents"])
    assert data["active_referral_count"] >= 0


def assert_loan_invariants(data: dict):
    """Loan invariants: balances are never negative and never exceed the draw."""
    assert data["outstanding_principal_cents"] >= 0
    assert data["accrued_interest_cents"] >= 0
    assert data["outstanding_principal_cents"] <= data["drawn_cents"]
    assert_cost_precision(data["outstanding_principal_cents"])