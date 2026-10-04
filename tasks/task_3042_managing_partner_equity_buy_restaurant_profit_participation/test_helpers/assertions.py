"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Per PRD §2.4 every entity carries the full
common set (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_label}.version must be an integer"


def assert_partner(data: dict):
    assert_common_fields(data, "Partner")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["role_in_program"] in ["MANAGING_PARTNER", "MARKET_PARTNER"]
    assert data["status"] in [
        "CANDIDATE",
        "IN_TRAINING",
        "TRAINING_EXTENDED",
        "CERTIFIED",
        "PLACED",
        "WITHDRAWN",
    ]
    assert isinstance(data["training_weeks_accrued"], int)


def assert_market_group(data: dict):
    assert_common_fields(data, "MarketGroup")
    assert data["status"] in ["FORMING", "ACTIVE", "DISSOLVED"]


def assert_restaurant(data: dict):
    assert_common_fields(data, "Restaurant")
    assert data["status"] in ["PRE_OPENING", "ACTIVE", "CLOSED"]


def assert_contract(data: dict):
    assert_common_fields(data, "ManagingPartnerContract")
    assert data["status"] in [
        "DRAFT",
        "PENDING_FUNDING",
        "ACTIVE",
        "RENEWAL_OFFERED",
        "BUYOUT_PENDING",
        "SETTLED",
        "TRANSFERRED",
        "LAPSED",
        "EXPIRED",
    ]
    assert isinstance(data["buy_in_required_cents"], int)
    assert isinstance(data["buy_in_escrow_cents"], int)
    assert isinstance(data["capital_account_cents"], int)
    assert isinstance(data["renewed_count"], int)


def assert_buy_in_payment(data: dict):
    assert_common_fields(data, "BuyInPayment")
    assert data["status"] in ["POSTED", "REFUNDED"]
    assert isinstance(data["amount_cents"], int)


def assert_agreement(data: dict):
    assert_common_fields(data, "MarketPartnerAgreement")
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert data["basis"] in ["NET_GROUP_BASIS", "PER_RESTAURANT_POSITIVE"]


def assert_profit_period(data: dict):
    assert_common_fields(data, "ProfitPeriod")
    assert data["status"] in ["OPEN", "COMPUTED", "FINALIZED", "REOPENED", "LOCKED"]


def assert_line_item(data: dict):
    assert_common_fields(data, "ProfitStatementLineItem")
    assert data["category"] in [
        "REVENUE",
        "COST_OF_GOODS",
        "LABOR",
        "CORPORATE_ADMIN_FEE",
        "CORPORATE_MARKETING_FEE",
        "MEAT_WASTE_CHARGE",
        "ADJUSTMENT",
    ]
    assert data["entry_status"] in ["PROVISIONAL", "FINALIZED"]
    assert data["partner_basis"] in ["INCLUDED", "EXCLUDED"]


def assert_yield_standard(data: dict):
    assert_common_fields(data, "YieldStandard")
    assert isinstance(data["active"], bool)


def assert_meat_cut_batch(data: dict):
    assert_common_fields(data, "MeatCutBatch")
    assert data["status"] in [
        "RECORDED",
        "AUDITED_CONFORMING",
        "VARIANCE_CONFIRMED",
        "VARIANCE_WAIVED",
    ]


def assert_award_program(data: dict):
    assert_common_fields(data, "AwardProgram")
    assert data["program_type"] in ["CONFERENCE", "STOCK_GRANT"]
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_award_grant(data: dict):
    assert_common_fields(data, "AwardGrant")
    assert data["status"] in ["EARNED", "VESTING", "VESTED", "FORFEITED"]


def assert_dispute_case(data: dict):
    assert_common_fields(data, "DisputeCase")
    assert data["status"] in [
        "SUBMITTED",
        "UNDER_REVIEW",
        "EVIDENCE_REQUESTED",
        "RESOLVED_UPHELD",
        "RESOLVED_ADJUSTED",
        "ESCALATED",
        "WITHDRAWN",
    ]


def assert_buyout_order(data: dict):
    assert_common_fields(data, "BuyoutOrder")
    assert data["status"] in ["DRAFT", "APPROVED", "PAID"]


def assert_allocation_conservation(period: dict):
    """The finalize-time allocation conservation invariant (PRD §3.6)."""
    assert (
        period["partner_share_cents"]
        + period["market_override_cents"]
        + period["corporate_retained_cents"]
        == period["final_distributable_profit_cents"]
    ), "partner_share + market_override + corporate_retained must equal final profit"
