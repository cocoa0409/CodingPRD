"""Entity assertions and domain invariant checkers for the SMA platform."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ASSET_CLASSES = ["US_EQUITY", "GLOBAL_EQUITY", "FIXED_INCOME", "CASH_EQUIV"]
MODEL_VERSION_STATUSES = [
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "PUBLISHED",
    "SUPERSEDED",
]
DISTRIBUTION_STATUSES = ["PENDING", "ACTIVE", "LAPSED"]
IMPLEMENTATION_STATUSES = ["PENDING_IMPLEMENTATION", "SYNCED", "DRIFTED", "SUSPENDED"]
BILLING_STATUSES = ["CURRENT", "INVOICED", "DELINQUENT", "WRITTEN_OFF"]
RESTRICTION_TYPES = ["DO_NOT_BUY", "DO_NOT_HOLD", "MAX_POSITION"]
RESTRICTION_STATUSES = ["ACTIVE", "LIFTED"]
ORDER_STATUSES = ["PROPOSED", "BLOCKED", "ALLOCATED", "CANCELLED", "STALE"]
ORDER_SIDES = ["BUY", "SELL"]
ORDER_SOURCES = ["IMPLEMENTATION", "REBALANCE"]
BLOCK_STATUSES = ["OPEN", "FILLED", "ALLOCATED"]
TAX_LOT_STATUSES = ["OPEN", "CLOSED", "REVERSED"]
TAX_LOT_ORIGINS = ["TRANSFER_IN", "TRADE"]
HARVEST_STATUSES = ["PROPOSED", "APPROVED", "EXECUTED", "REJECTED", "SUPERSEDED"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PAID", "VOIDED", "WRITTEN_OFF"]


def assert_housekeeping(data: dict, entity_name: str = "resource"):
    """id / created_at / updated_at / version are carried by every resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_security(data: dict):
    assert_housekeeping(data, "Security")
    assert isinstance(data["ticker"], str) and data["ticker"].isupper()
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["asset_class"] in ASSET_CLASSES
    assert isinstance(data["last_price_cents"], int) and data["last_price_cents"] >= 1
    assert isinstance(data["restricted_globally"], bool)


def assert_sponsor(data: dict):
    assert_housekeeping(data, "Sponsor")
    assert isinstance(data["name"], str)
    assert isinstance(data["platform_code"], str)
    assert 0 <= data["revenue_share_bps"] <= 9000
    assert 0 <= data["implementation_lag_days"] <= 10
    assert data["min_account_value_cents"] >= 0
    assert data["account_count"] >= 0


def assert_model(data: dict):
    assert_housekeeping(data, "Model")
    assert isinstance(data["manager_name"], str)
    assert isinstance(data["strategy_code"], str)
    assert data["asset_class"] in ASSET_CLASSES
    assert 1 <= data["base_fee_bps"] <= 500
    assert 1 <= data["drift_threshold_bps"] <= 10000
    assert data["version_count"] >= 0


def assert_model_version(data: dict):
    assert_housekeeping(data, "ModelVersion")
    assert is_valid_uuid(data["model_id"])
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["status"] in MODEL_VERSION_STATUSES
    assert isinstance(data["sleeves"], list)
    assert data["sleeve_count"] == len(data["sleeves"])
    assert data["total_target_weight_bps"] == sum(
        s["target_weight_bps"] for s in data["sleeves"]
    )
    assert data["distribution_count"] >= 0


def assert_distribution(data: dict):
    assert_housekeeping(data, "SponsorDistribution")
    assert is_valid_uuid(data["sponsor_id"])
    assert is_valid_uuid(data["model_version_id"])
    assert is_valid_uuid(data["model_id"])
    assert data["status"] in DISTRIBUTION_STATUSES
    assert is_iso8601_timestamp(data["effective_from"])


def assert_account(data: dict):
    assert_housekeeping(data, "Account")
    assert is_valid_uuid(data["sponsor_id"])
    assert is_valid_uuid(data["model_id"])
    assert isinstance(data["account_number"], str)
    assert data["implementation_status"] in IMPLEMENTATION_STATUSES
    assert data["billing_status"] in BILLING_STATUSES
    assert isinstance(data["cash_cents"], int)
    assert 0 <= data["cash_reserve_bps"] <= 2000
    assert isinstance(data["market_value_cents"], int)
    assert data["drift_basis"] in ["SETTLED", "TRADE_DATE"]
    assert isinstance(data["tax_overlay_enabled"], bool)
    assert data["harvest_budget_cents"] >= 0
    assert data["realized_loss_ytd_cents"] >= 0
    assert data["fees_billed_ytd_cents"] >= 0
    assert isinstance(data["implemented_late"], bool)
    assert data["next_order_sequence"] >= 1


def assert_restriction(data: dict):
    assert_housekeeping(data, "AccountRestriction")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["security_id"])
    assert data["restriction_type"] in RESTRICTION_TYPES
    assert data["status"] in RESTRICTION_STATUSES
    if data["restriction_type"] == "MAX_POSITION":
        assert 1 <= data["max_position_bps"] <= 10000
    else:
        assert data.get("max_position_bps") is None


def assert_trade_order(data: dict):
    assert_housekeeping(data, "TradeOrder")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["security_id"])
    assert is_valid_uuid(data["model_version_id"])
    assert data["status"] in ORDER_STATUSES
    assert data["side"] in ORDER_SIDES
    assert data["source"] in ORDER_SOURCES
    assert isinstance(data["shares"], int) and data["shares"] >= 1
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["target_shares"], int)
    assert isinstance(data["effective_weight_bps"], int)
    assert isinstance(data["allocated_shares"], int)


def assert_block(data: dict):
    assert_housekeeping(data, "Block")
    assert is_valid_uuid(data["security_id"])
    assert data["side"] in ORDER_SIDES
    assert data["status"] in BLOCK_STATUSES
    assert data["requested_shares"] >= 0
    assert data["filled_shares"] >= 0
    assert data["order_count"] >= 0
    assert_block_share_conservation(data)


def assert_block_share_conservation(block: dict):
    """filled_shares always equals allocated_shares plus unallocated_shares."""
    assert block["filled_shares"] == block["allocated_shares"] + block["unallocated_shares"], (
        "Block conservation broken: filled_shares "
        f"{block['filled_shares']} != allocated_shares {block['allocated_shares']} "
        f"+ unallocated_shares {block['unallocated_shares']}"
    )


def assert_tax_lot(data: dict):
    assert_housekeeping(data, "TaxLot")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["security_id"])
    assert data["status"] in TAX_LOT_STATUSES
    assert data["origin"] in TAX_LOT_ORIGINS
    assert is_iso8601_timestamp(data["open_date"])
    assert isinstance(data["shares_open"], int) and data["shares_open"] >= 0
    assert isinstance(data["shares_closed"], int) and data["shares_closed"] >= 0
    assert isinstance(data["cost_basis_cents"], int)
    assert isinstance(data["sequence_number"], int)


def assert_harvest_proposal(data: dict):
    assert_housekeeping(data, "HarvestProposal")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["security_id"])
    assert data["status"] in HARVEST_STATUSES
    assert isinstance(data["shares"], int) and data["shares"] >= 1
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["target_loss_cents"], int)
    assert isinstance(data["proposed_loss_cents"], int)
    assert data["proposed_loss_cents"] >= 0


def assert_fee_invoice(data: dict):
    assert_housekeeping(data, "FeeInvoice")
    assert is_valid_uuid(data["account_id"])
    assert data["status"] in INVOICE_STATUSES
    assert isinstance(data["billing_days"], int) and data["billing_days"] >= 1
    assert data["average_daily_value_cents"] >= 0
    assert_invoice_split_invariants(data)


def assert_invoice_split_invariants(invoice: dict):
    """gross is the sum of the three rounded tiers; the three shares add back."""
    assert invoice["gross_fee_cents"] == (
        invoice["tier1_fee_cents"] + invoice["tier2_fee_cents"] + invoice["tier3_fee_cents"]
    ), "gross_fee_cents must equal the sum of the three independently rounded tier fees"
    assert invoice["gross_fee_cents"] == (
        invoice["sponsor_share_cents"]
        + invoice["platform_share_cents"]
        + invoice["manager_share_cents"]
    ), "the three revenue shares must add back to exactly gross_fee_cents"


def assert_all_integers(data: dict, *fields):
    for field in fields:
        assert isinstance(data[field], int), f"{field} must be a whole number of units"


def assert_version_advanced_by(new_row: dict, old_row: dict, expected_delta: int = 1):
    actual = new_row["version"] - old_row["version"]
    assert actual == expected_delta, (
        f"Expected version to advance by {expected_delta}, "
        f"went {old_row['version']} -> {new_row['version']}"
    )
