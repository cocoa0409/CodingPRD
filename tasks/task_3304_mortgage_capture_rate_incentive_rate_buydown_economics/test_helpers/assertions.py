"""Entity shape assertions used by the fixtures and tests."""

from prd_bench_local_runner.testing import assert_cost_precision, is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def assert_community(data: dict):
    _assert_common(data, "Community")
    assert data["program_status"] in ("ACTIVE", "RESTRICTED", "SUSPENDED")
    assert data["incentive_policy_code"] in ("STANDARD", "PREMIUM", "CLEARANCE")
    for field in (
        "affiliated_units",
        "funded_units",
        "capture_rate_bps",
        "incentive_spend_cents",
        "forward_units_committed",
    ):
        assert isinstance(data[field], int), f"Community.{field} must be an int"


def assert_forward_commitment(data: dict):
    _assert_common(data, "ForwardCommitment")
    assert data["commitment_status"] in ("OPEN", "EXHAUSTED", "EXPIRED", "CLOSED")
    assert data["units_available"] == (
        data["committed_units"] - data["units_drawn"] + data["units_released"]
    ), "units_available must equal committed_units - units_drawn + units_released"


def assert_home_site(data: dict):
    _assert_common(data, "HomeSite")
    assert data["home_site_status"] in ("AVAILABLE", "UNDER_CONTRACT", "SOLD")
    assert data["construction_stage"] in (
        "NOT_STARTED", "FOUNDATION", "FRAMING", "DRYWALL", "FINISH", "COMPLETE",
    )
    assert data["base_price_cents"] > 0


def assert_buyer(data: dict):
    _assert_common(data, "Buyer")
    assert data["buyer_status"] in ("PROSPECT", "QUALIFIED", "CONTRACTED", "WITHDRAWN")
    assert isinstance(data["affiliated_lender_selected"], bool)
    assert isinstance(data["steering_protection_flag"], bool)


def assert_contract(data: dict):
    _assert_common(data, "HomeSaleContract")
    assert data["contract_status"] in ("PENDING", "LOCKED", "APPROVED", "CLOSED", "CANCELLED")
    assert data["cancellation_reason"] in (
        "BUYER_DEFAULT", "CONSTRUCTION_DELAY", "FINANCING_DENIED", "RATE_SHOCK", None,
    )


def assert_loan_application(data: dict):
    _assert_common(data, "LoanApplication")
    assert data["application_status"] in ("SUBMITTED", "QUALIFIED", "DENIED", "EXPIRED")
    assert data["lock_waiver_status"] in ("NOT_REQUESTED", "REQUESTED", "GRANTED", "REFUSED")
    assert 300 <= data["qualification_score"] <= 850
    assert data["uw_precedence"] == (
        f"{data['application_status']}_{data['lock_waiver_status']}"
    ), "uw_precedence must join the two state dimensions"


def assert_rate_lock(data: dict):
    _assert_common(data, "RateLock")
    assert data["lock_status"] in ("ACTIVE", "CONSUMED", "EXPIRED", "VOIDED")
    assert is_iso8601_timestamp(data["lock_start_iso"])
    assert is_iso8601_timestamp(data["lock_expires_iso"])


def assert_incentive_allocation(data: dict):
    _assert_common(data, "IncentiveAllocation")
    assert data["allocation_status"] in ("PENDING", "RESERVED", "APPLIED", "REVERSED")
    assert data["bucket"] in ("PRICE_REDUCTION", "CLOSING_COSTS", "RATE_BUYDOWN")
    assert data["spill_to_bucket"] in (
        "PRICE_REDUCTION", "CLOSING_COSTS", "RATE_BUYDOWN", None,
    )
    assert_cost_precision(data["allocation_total_cents"])


def assert_buydown_record(data: dict):
    _assert_common(data, "BuydownCostRecord")
    assert data["record_status"] in ("DRAFT", "BOOKED", "REVERSED")
    assert data["allowed_buydown_cost_cents"] >= 0


def assert_disclosure(data: dict):
    _assert_common(data, "ABADisclosure")
    assert data["disclosure_status"] in ("ISSUED", "ACKNOWLEDGED", "CURING", "WAIVED")
    assert data["disclosure_type"] in (
        "AFFILIATED_BUSINESS_ARRANGEMENT", "STEERING_PROHIBITION", "RATE_BUYDOWN_TERMS",
    )
    assert is_iso8601_timestamp(data["cure_deadline_iso"])


def assert_deposit_forfeiture(data: dict):
    _assert_common(data, "DepositForfeiture")
    assert data["forfeiture_status"] in ("PROPOSED", "FINALIZED", "VOIDED")
    assert data["statute_class"] in (
        "FULL_FORFEITURE", "PARTIAL_FORFEITURE", "RESTITUTION_REQUIRED",
    )


def assert_community_invariants(data: dict):
    """Invariants that hold after any operation on a community."""
    assert data["affiliated_units"] >= 0
    assert data["funded_units"] >= 0
    assert data["affiliated_units"] <= data["funded_units"]
    assert data["capture_rate_bps"] >= 0
    assert data["incentive_spend_cents"] >= 0


def assert_contract_invariants(data: dict):
    """Invariants that hold after any operation on a sale contract."""
    assert data["incentive_allocated_cents"] >= 0
    assert data["incentive_budget_cents"] >= 0
    assert data["deposit_held_cents"] >= 0